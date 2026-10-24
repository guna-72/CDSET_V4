from __future__ import annotations
"""
Multi-provider LLM key pool for the optional AI diagnosis path
(app/diagnosis.py). Supports six providers and any number of keys per
provider, with a rotation mechanism that:

  1. spreads load round-robin across every configured (provider, key)
     pair — each diagnose_run() call starts from the next position in
     the pool, even when every call succeeds first try, and
  2. fails over automatically to the next entry in the pool if the
     current one errors (bad key, rate limit, provider outage), trying
     every configured key across every provider before giving up.

Configuration is via environment variables — one per provider, accepting
a comma- and/or newline-separated block so you can paste as many keys as
you have straight in:

    ANTHROPIC_API_KEYS=sk-ant-...,sk-ant-...
    OPENAI_API_KEYS=sk-...
    GEMINI_API_KEYS=AIza...
    DEEPSEEK_API_KEYS=sk-...
    GROQ_API_KEYS=gsk_...
    OPENROUTER_API_KEYS=sk-or-...

The singular form (e.g. ANTHROPIC_API_KEY) is also read and folded into
that provider's pool, for compatibility with a single-key setup. Empty
entries and duplicates are dropped; nothing here ever logs a raw key —
errors and audit trails only ever see a masked form (see _mask below).

This module makes network calls; it has never been exercised against a
live provider in this sandbox (no network access here — confirmed
earlier in this session). It's exercised by tests/test_llm_providers.py
against mocked provider calls instead, which cover the parsing,
rotation, and failover logic that doesn't require the network.
"""
import json
import os
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

_ENV_VAR_BY_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEYS",
    "openai": "OPENAI_API_KEYS",
    "gemini": "GEMINI_API_KEYS",
    "deepseek": "DEEPSEEK_API_KEYS",
    "groq": "GROQ_API_KEYS",
    "openrouter": "OPENROUTER_API_KEYS",
    "mistral": "MISTRAL_API_KEYS",
    "cohere": "COHERE_API_KEYS",
    "together": "TOGETHER_API_KEYS",
    "xai": "XAI_API_KEYS",
    "huggingface": "HUGGINGFACE_API_KEYS",
}
_SINGULAR_ENV_VAR_BY_PROVIDER = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "together": "TOGETHER_API_KEY",
    "xai": "XAI_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
}

# Ordered so that, all else equal, rotation tends to try genuinely-free
# providers first. Verified current as of this pass (search-checked, not
# just training-data recall — free-tier terms shift, re-verify before
# trusting this blindly months from now):
#   - groq: real free tier, no card, but RATE-LIMITED PER ACCOUNT/ORG —
#     multiple keys from the SAME Groq account share one limit pool, so
#     they don't multiply your quota the way keys from different
#     providers do.
#   - gemini: real free tier via Google AI Studio, similarly limited per
#     Google Cloud project rather than per key.
#   - openrouter: free via the model default below (openrouter/free, an
#     official OpenRouter router that always resolves to a $0 model) —
#     genuinely different infrastructure per call, so it's a good
#     complement to groq/gemini rather than a duplicate of their limits.
#   - deepseek, openai, anthropic: no standing free tier as of this
#     pass — deepseek's own free promo models and its free variants on
#     OpenRouter have both been discontinued; these three need a paid
#     key to do anything.
_PROVIDER_ORDER = ["groq", "gemini", "openrouter", "deepseek", "openai", "anthropic", "mistral", "cohere", "together", "xai", "huggingface"]


class AllProvidersFailedError(Exception):
    pass


def _parse_keys(raw: str) -> list[str]:
    """Accepts a comma- and/or newline-separated pasted block. Trims
    whitespace, drops empty entries, de-duplicates while preserving
    order."""
    if not raw:
        return []
    parts = raw.replace("\n", ",").split(",")
    seen = set()
    out = []
    for p in parts:
        k = p.strip()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


_SETTINGS_KEYS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "settings_keys.json"
)
_RUNTIME_SETTINGS = {}


def get_settings_keys() -> dict:
    """Read API keys saved in user settings."""
    global _RUNTIME_SETTINGS
    if _RUNTIME_SETTINGS:
        return dict(_RUNTIME_SETTINGS)
    if os.path.exists(_SETTINGS_KEYS_FILE):
        try:
            with open(_SETTINGS_KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def save_settings_keys(keys: dict) -> dict:
    """Save API keys in user settings."""
    global _RUNTIME_SETTINGS
    cleaned = {str(k).lower().strip(): str(v).strip() for k, v in (keys or {}).items() if str(v).strip()}
    _RUNTIME_SETTINGS = dict(cleaned)
    try:
        os.makedirs(os.path.dirname(_SETTINGS_KEYS_FILE), exist_ok=True)
        with open(_SETTINGS_KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)
    except Exception as e:
        print(f"[llm_providers] Failed to write settings_keys.json: {e}")
    return cleaned


def load_keys() -> dict:
    """provider -> ordered list of configured keys.
    RULE:
    1. First check in settings: if a key exists in settings for a provider,
       USE THAT KEY.
    2. Else check the API keys in the env file / os.environ.
    """
    settings = get_settings_keys()
    keys_by_provider = {}
    for provider in _PROVIDER_ORDER:
        provider_keys = []
        # Step 1: Check in settings first
        val = settings.get(provider) or settings.get(provider.lower())
        if val and isinstance(val, str) and val.strip():
            provider_keys = _parse_keys(val.strip())

        # Step 2: Else check the API keys in the env file (.env / os.environ)
        if not provider_keys:
            env_keys = _parse_keys(os.environ.get(_ENV_VAR_BY_PROVIDER[provider], ""))
            singular = os.environ.get(_SINGULAR_ENV_VAR_BY_PROVIDER[provider], "").strip()
            if singular and singular not in env_keys:
                env_keys.append(singular)
            provider_keys = env_keys

        if provider_keys:
            keys_by_provider[provider] = provider_keys
    return keys_by_provider


def get_keys_source_info() -> dict:
    """Returns details for each provider showing if the key comes from 'settings', '.env', or 'none'."""
    settings = get_settings_keys()
    info = {}
    for provider in _PROVIDER_ORDER:
        val = settings.get(provider) or settings.get(provider.lower())
        has_setting = bool(val and str(val).strip())
        env_keys = _parse_keys(os.environ.get(_ENV_VAR_BY_PROVIDER[provider], ""))
        singular = os.environ.get(_SINGULAR_ENV_VAR_BY_PROVIDER[provider], "").strip()
        has_env = bool(env_keys or singular)
        if has_setting:
            info[provider] = {
                "source": "settings",
                "active": True,
                "masked": _mask(val.strip().split(",")[0]),
            }
        elif has_env:
            key_sample = env_keys[0] if env_keys else singular
            info[provider] = {
                "source": "env",
                "active": True,
                "masked": _mask(key_sample),
            }
        else:
            info[provider] = {"source": "none", "active": False, "masked": None}
    return info


def _mask(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-2:]}"


class KeyPool:
    """Thread-safe rotation state. One instance shared process-wide."""

    def __init__(self):
        self._lock = threading.Lock()
        self._start = 0

    def entries(self) -> list:
        flat = []
        for provider, keys in load_keys().items():
            for key in keys:
                flat.append((provider, key))
        return flat

    def any_configured(self) -> bool:
        return bool(self.entries())

    def rotation_order(self) -> list:
        """Full pool starting at the current rotation position; advances
        the position for the next call. Re-reads settings and env vars each time,
        so keys added/removed between calls take effect immediately."""
        pool = self.entries()
        if not pool:
            return []
        with self._lock:
            start = self._start % len(pool)
            self._start = (self._start + 1) % len(pool)
        return pool[start:] + pool[:start]


_POOL = KeyPool()

_ENABLE_ENV_VAR = "ENABLE_LLM_DIAGNOSIS"
_TRUTHY = {"1", "true", "yes", "on"}


def any_keys_configured() -> bool:
    return _POOL.any_configured()


def explicitly_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR, "").strip().lower() in _TRUTHY


def diagnosis_enabled() -> bool:
    """The real gate diagnose_run() checks. Enabled if keys are present
    and either explicit opt-in env var is set OR keys are configured in settings."""
    return any_keys_configured() and (explicitly_enabled() or bool(get_settings_keys()))


def configured_providers() -> list:
    return sorted(load_keys().keys())


# --------------------------------------------------------------- providers

def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _post_json(url: str, headers: dict, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _call_anthropic(key, model, system_prompt, user_content, timeout):
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
        {"model": model, "max_tokens": 1000, "system": system_prompt,
         "messages": [{"role": "user", "content": user_content}]},
        timeout,
    )
    text = "".join(b.get("text", "") for b in data.get("content", []))
    return _extract_json(text)


def _call_openai_compatible(key, model, system_prompt, user_content, timeout, base_url, extra_headers=None):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    headers.update(extra_headers or {})
    data = _post_json(
        base_url, headers,
        {"model": model, "max_tokens": 1000, "response_format": {"type": "json_object"},
         "messages": [{"role": "system", "content": system_prompt},
                       {"role": "user", "content": user_content}]},
        timeout,
    )
    text = data["choices"][0]["message"]["content"]
    return _extract_json(text)


def _call_openai(key, model, system_prompt, user_content, timeout):
    return _call_openai_compatible(key, model, system_prompt, user_content, timeout,
                                    "https://api.openai.com/v1/chat/completions")


def _call_deepseek(key, model, system_prompt, user_content, timeout):
    return _call_openai_compatible(key, model, system_prompt, user_content, timeout,
                                    "https://api.deepseek.com/chat/completions")


def _call_groq(key, model, system_prompt, user_content, timeout):
    return _call_openai_compatible(key, model, system_prompt, user_content, timeout,
                                    "https://api.groq.com/openai/v1/chat/completions")


def _call_openrouter(key, model, system_prompt, user_content, timeout):
    # OpenRouter recommends (not requires) identifying your app; harmless
    # to include, and it's not a secret.
    return _call_openai_compatible(key, model, system_prompt, user_content, timeout,
                                    "https://openrouter.ai/api/v1/chat/completions",
                                    extra_headers={"HTTP-Referer": "https://chaos-tutor.local",
                                                    "X-Title": "Chaos Tutor"})


def _call_gemini(key, model, system_prompt, user_content, timeout):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    data = _post_json(
        url, {"Content-Type": "application/json"},
        {"system_instruction": {"parts": [{"text": system_prompt}]},
         "contents": [{"role": "user", "parts": [{"text": user_content}]}],
         "generationConfig": {"response_mime_type": "application/json", "maxOutputTokens": 1000}},
        timeout,
    )
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _extract_json(text)



# Lightweight API-key health checks. These calls only ask the provider for
# metadata (usually its model list); they do not send a user prompt and the
# supplied key is never returned to the caller or logged. A provider cannot
# be inferred for every arbitrary secret, so unknown/custom keys are reported
# as "format_only" unless a compatible endpoint is supplied by the caller.
_KEY_CHECKS = {
    "openai": {"url": "https://api.openai.com/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "groq": {"url": "https://api.groq.com/openai/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "deepseek": {"url": "https://api.deepseek.com/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "openrouter": {"url": "https://openrouter.ai/api/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "anthropic": {"url": "https://api.anthropic.com/v1/models", "headers": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}},
    "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/models", "headers": lambda k: {}},
    "mistral": {"url": "https://api.mistral.ai/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "cohere": {"url": "https://api.cohere.com/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "together": {"url": "https://api.together.xyz/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "xai": {"url": "https://api.x.ai/v1/models", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
    "huggingface": {"url": "https://huggingface.co/api/models?limit=1", "headers": lambda k: {"Authorization": f"Bearer {k}"}},
}

def _looks_like_provider_key(provider: str, key: str) -> bool:
    k = (key or "").strip()
    if not k:
        return False
    prefixes = {
        "groq": ("gsk_",), "openai": ("sk-",), "deepseek": ("sk-",),
        "openrouter": ("sk-or-",), "anthropic": ("sk-ant-",), "gemini": ("AIza", "AQ."),
        "mistral": (), "cohere": (), "together": (), "xai": ("xai-",), "huggingface": ("hf_",),
    }
    p = prefixes.get(provider, ())
    return (not p) or any(k.startswith(x) for x in p)

def check_api_key(provider: str, key: str, endpoint: str | None = None, timeout: float = 8.0) -> dict:
    provider = (provider or "auto").strip().lower()
    key = (key or "").strip()
    if not key:
        return {"status": "invalid", "provider": provider, "message": "Enter an API key.", "key": "***"}
    if provider == "auto":
        detected = []
        for name in _KEY_CHECKS:
            if _looks_like_provider_key(name, key):
                detected.append(name)
        if len(detected) == 1:
            provider = detected[0]
        elif key.startswith("sk-or-"):
            provider = "openrouter"
        elif key.startswith("sk-ant-"):
            provider = "anthropic"
        elif key.startswith("gsk_"):
            provider = "groq"
        elif key.startswith("AIza") or key.startswith("AQ."):
            provider = "gemini"
        elif key.startswith("hf_"):
            provider = "huggingface"
        else:
            provider = "custom"
    if not endpoint and provider == "custom":
        return {"status": "format_only", "provider": provider, "message": "Unknown key type. Supply a compatible verification endpoint to perform a live check.", "key": _mask(key)}
    if endpoint:
        url = endpoint.strip()
        parsed = urlparse(url)
        allowed = {h.strip().lower() for h in os.environ.get("CHAOS_TUTOR_ALLOWED_KEY_CHECK_HOSTS", "").split(",") if h.strip()}
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in allowed:
            return {"status": "endpoint_not_allowed", "provider": provider, "message": "Custom endpoint is not allow-listed by the backend. Add its hostname to CHAOS_TUTOR_ALLOWED_KEY_CHECK_HOSTS.", "key": _mask(key)}
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    else:
        cfg = _KEY_CHECKS.get(provider)
        if not cfg:
            return {"status": "format_only", "provider": provider, "message": "Provider is not in the built-in checker. Use a compatible custom endpoint.", "key": _mask(key)}
        url = cfg["url"]
        headers = cfg["headers"](key)
        headers["Accept"] = "application/json"
        if provider == "gemini":
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}key={key}"
    if not _looks_like_provider_key(provider, key) and provider != "custom":
        return {"status": "invalid_format", "provider": provider, "message": "The key does not match the usual format for this provider.", "key": _mask(key)}
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            return {"status": "working", "provider": provider, "http_status": code, "message": "The provider accepted the key.", "key": _mask(key)}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return {"status": "invalid", "provider": provider, "http_status": e.code, "message": "The provider rejected the API key.", "key": _mask(key)}
        if e.code == 429:
            return {"status": "rate_limited", "provider": provider, "http_status": e.code, "message": "The key was accepted far enough to reach rate limiting. Try again later.", "key": _mask(key)}
        return {"status": "provider_error", "provider": provider, "http_status": e.code, "message": "The provider returned an error while checking the key.", "key": _mask(key)}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "unreachable", "provider": provider, "message": "The provider could not be reached. This does not prove the key is invalid.", "key": _mask(key)}

def _provider_config(provider: str) -> dict:
    registry = {
        "anthropic": {"call": _call_anthropic, "model_env": "ANTHROPIC_MODEL", "default_model": "claude-sonnet-4-6"},
        "openai": {"call": _call_openai, "model_env": "OPENAI_MODEL", "default_model": "gpt-4o-mini"},
        "gemini": {"call": _call_gemini, "model_env": "GEMINI_MODEL", "default_model": "gemini-3.5-flash-lite"},
        "deepseek": {"call": _call_deepseek, "model_env": "DEEPSEEK_MODEL", "default_model": "deepseek-chat"},
        "groq": {"call": _call_groq, "model_env": "GROQ_MODEL", "default_model": "llama-3.3-70b-versatile"},
        "openrouter": {"call": _call_openrouter, "model_env": "OPENROUTER_MODEL",
                       # openrouter/free is OpenRouter's own official router — it always
                       # resolves to a $0 model and filters for the features this call
                       # needs (JSON output), so it stays free even as the underlying
                       # free-model lineup rotates. A specific "openai/..." model here
                       # would be a REAL, BILLED OpenRouter pass-through call — don't
                       # default to one.
                       "default_model": "openrouter/free"},
    }
    return registry[provider]


def diagnose_with_llm(system_prompt: str, user_content: str, timeout: float = 30) -> dict:
    """Tries every configured (provider, key) pair in rotation order,
    starting from wherever the pool left off last call, until one
    returns a parsed JSON object or the whole pool is exhausted. Raises
    AllProvidersFailedError (with masked keys only) if every entry
    fails — app/diagnosis.py catches this and falls back to the
    rule-based diagnoser."""
    pool = _POOL.rotation_order()
    if not pool:
        raise AllProvidersFailedError("no LLM API keys configured")
    errors = []
    for provider, key in pool:
        cfg = _provider_config(provider)
        model = os.environ.get(cfg["model_env"], cfg["default_model"])
        try:
            result = cfg["call"](key, model, system_prompt, user_content, timeout)
            if not isinstance(result, dict):
                raise ValueError("provider did not return a JSON object")
            return result
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                ValueError, KeyError, json.JSONDecodeError, OSError) as e:
            errors.append(f"{provider}[{_mask(key)}]: {type(e).__name__}: {e}")
            continue
    raise AllProvidersFailedError(
        f"all {len(pool)} configured key(s) failed — " + "; ".join(errors)
    )
