import os
import json
import re

from dotenv import load_dotenv
from google import genai
from google.genai import types

from prompts import create_prompt

_dir = os.path.dirname(os.path.abspath(__file__))
_local_env = os.path.join(_dir, ".env")
if os.path.exists(_local_env):
    load_dotenv(_local_env)
load_dotenv()


# ------------------------------------------------
# Load all Gemini API keys (supports numbered keys and comma-separated list)
# ------------------------------------------------

API_KEYS = []
# Numbered keys GEMINI_API_KEY_1 .. GEMINI_API_KEY_10
for i in range(1, 11):
    val = os.getenv(f"GEMINI_API_KEY_{i}")
    if val and val.strip() and val.strip() not in API_KEYS:
        API_KEYS.append(val.strip())

# Comma-separated list from GEMINI_API_KEYS
if os.getenv("GEMINI_API_KEYS"):
    for part in os.getenv("GEMINI_API_KEYS", "").replace("\n", ",").split(","):
        k = part.strip()
        if k and k not in API_KEYS:
            API_KEYS.append(k)

# Models to try in order of speed and availability (fastest lite models first)
_preferred = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
_raw_models = [
    _preferred,
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.8-flash",
]
CANDIDATE_MODELS = []
for _m in _raw_models:
    if _m and _m not in CANDIDATE_MODELS:
        CANDIDATE_MODELS.append(_m)

# Request timeout in seconds for each Gemini API call (Google API requires minimum 10s deadline)
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "12"))

# In-memory caching & rotation tracking for blazing speed
_EXPLANATION_CACHE = {}
_LAST_WORKING_KEY_INDEX = 0
_LAST_WORKING_MODEL = "gemini-3.5-flash-lite"


# ------------------------------------------------
# JSON extraction helper
# ------------------------------------------------

def extract_json(text):
    """
    Strip markdown code fences and parse JSON from Gemini's response.
    Tries direct parse first; falls back to regex extraction of the
    first complete JSON object in the text.
    """
    text = text.strip()

    # Remove markdown code blocks
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    # Try direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try finding the first balanced JSON object
    # Walk the string to find matching braces (handles nested objects)
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError("Gemini did not return valid JSON.")


# ------------------------------------------------
# Main response generator
# ------------------------------------------------

def generate_ai_response(fault_data, custom_api_key: str | None = None):
    """
    Send fault_data to Gemini and return a structured analysis dict.
    First checks if a key is provided from settings; if present, uses that key.
    Otherwise, checks and falls back to API keys in the .env file.
    """
    global _LAST_WORKING_KEY_INDEX, _LAST_WORKING_MODEL

    # 0. Instant Cache Lookup (<1ms)
    cache_key = (
        str(fault_data.get("fault", "")),
        str(fault_data.get("file", "")),
        str(fault_data.get("line", "")),
        str(fault_data.get("current_code", "")).strip()[:100],
    )
    if cache_key in _EXPLANATION_CACHE:
        print("[ai_tutor] Returning cached explanation and solved code instantly.")
        return dict(_EXPLANATION_CACHE[cache_key])

    # 1. First check in settings: if a key exists, use that key
    if custom_api_key and str(custom_api_key).strip():
        keys_to_try = [str(custom_api_key).strip()]
        print("[ai_tutor] generate_ai_response: Using API key from Settings (priority over .env).")
    else:
        # 2. Else check the API keys in the .env file
        raw_keys = list(API_KEYS)
        if len(raw_keys) > 1:
            # Start from the last known working key to avoid cycling through exhausted keys
            idx = _LAST_WORKING_KEY_INDEX % len(raw_keys)
            keys_to_try = raw_keys[idx:] + raw_keys[:idx]
        else:
            keys_to_try = raw_keys
        print(f"[ai_tutor] generate_ai_response: Using {len(keys_to_try)} API key(s) from .env.")

    # No API keys configured anywhere
    if not keys_to_try:
        print("[ai_tutor] No Gemini API keys configured in settings or .env — returning fallback.")
        return _no_keys_response(fault_data)

    prompt = create_prompt(fault_data)

    # Prioritize last working model
    models_to_try = list(CANDIDATE_MODELS)
    if _LAST_WORKING_MODEL in models_to_try:
        models_to_try.remove(_LAST_WORKING_MODEL)
        models_to_try.insert(0, _LAST_WORKING_MODEL)

    gen_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        max_output_tokens=2500,
        temperature=0.1,
    )

    # Try candidate API keys
    for key_number, api_key in enumerate(keys_to_try, start=1):
        try:
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=GEMINI_TIMEOUT * 1000  # milliseconds
                ),
            )

            response = None
            used_model = None
            for m in models_to_try:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=gen_config,
                    )
                    used_model = m
                    break
                except Exception as m_err:
                    print(f"[ai_tutor] Model {m} failed: {m_err}")
                    continue

            if response is None:
                raise RuntimeError("All candidate models failed for this key")

            response_text = response.text
            result = extract_json(response_text)

            # Guarantee all required fields exist
            _apply_defaults(result, fault_data)

            # Clean markdown fences from replacement_code if any
            if "replacement_code" in result and isinstance(result["replacement_code"], str):
                cleaned = result["replacement_code"].strip()
                cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned).strip()
                result["replacement_code"] = cleaned

            # Update cache and active indices
            _EXPLANATION_CACHE[cache_key] = result
            _LAST_WORKING_MODEL = used_model
            if api_key in API_KEYS:
                _LAST_WORKING_KEY_INDEX = API_KEYS.index(api_key)

            print(
                f"[ai_tutor] Gemini key succeeded in fast path "
                f"(model={used_model})."
            )

            return result

        except Exception as error:
            print(
                f"[ai_tutor] Gemini key attempt failed: {error}"
            )
            continue

    # All keys failed
    print("[ai_tutor] All candidate Gemini API keys failed — returning fallback.")
    return _all_keys_failed_response(fault_data)


# ------------------------------------------------
# Default value helpers
# ------------------------------------------------

def _apply_defaults(result, fault_data):
    """Ensure every required response field is present."""
    result.setdefault("fault",            fault_data.get("fault", "UNKNOWN"))
    result.setdefault("severity",         "MEDIUM")
    result.setdefault("error_location",   "Not specified")
    result.setdefault("problem",          "Problem could not be determined.")
    result.setdefault(
        "problematic_code",
        fault_data.get("current_code", "No code provided.")
    )
    result.setdefault("why_it_failed",          "No explanation provided.")
    result.setdefault("replacement_code",       "No replacement code generated.")
    result.setdefault("why_replacement_works",  "No explanation provided.")
    result.setdefault("recovery_steps",         ["Check the error and retry."])
    result.setdefault(
        "prevention",
        "Add proper error handling and monitoring."
    )

    rep = result.get("replacement_code")
    if isinstance(rep, str):
        rep_clean = re.sub(r"^```[a-zA-Z]*\n?", "", rep.strip())
        rep_clean = re.sub(r"\n?```$", "", rep_clean.strip())
        result["replacement_code"] = rep_clean


def _no_keys_response(fault_data):
    return {
        "fault":               fault_data.get("fault", "UNKNOWN"),
        "severity":            "UNKNOWN",
        "error_location":      "Not available",
        "problem":             "Gemini API keys are not configured.",
        "problematic_code":    fault_data.get("current_code", "No code provided."),
        "why_it_failed":       "AI analysis could not be performed — no API keys.",
        "replacement_code":    "",
        "why_replacement_works": "",
        "recovery_steps": [
            "Open the .env file in ai_tutor_backend/.",
            "Add at least one Gemini API key as GEMINI_API_KEY_1=...",
            "Restart the AI Tutor backend.",
        ],
        "prevention": "Keep valid Gemini API credentials configured in .env.",
    }


def _all_keys_failed_response(fault_data):
    return {
        "fault": fault_data.get("fault", "UNKNOWN"),
        "severity": "UNKNOWN",
        "error_location": (
            f"{fault_data.get('file', 'Unknown file')} : "
            f"line {fault_data.get('line', 'Unknown')}"
        ),
        "problem": (
            "The fault was received, but Gemini analysis "
            "could not be generated (all API keys failed)."
        ),
        "problematic_code": fault_data.get("current_code", "No code provided."),
        "why_it_failed":    "All configured Gemini API keys failed.",
        "replacement_code":       "",
        "why_replacement_works":  "",
        "recovery_steps": [
            "Check that GEMINI_API_KEY_1 (and others) are valid in .env.",
            "Check Gemini API quota at https://aistudio.google.com/.",
            "Check internet connectivity from the backend machine.",
            "Try the request again in a few seconds.",
        ],
        "prevention": (
            "Monitor API availability and configure "
            "multiple valid API keys for automatic failover."
        ),
    }


# ------------------------------------------------
# Conversational AI Tutor Chat
# ------------------------------------------------

def chat_with_ai(question: str, fault: str = "", context: str = "", history: list | None = None, custom_api_key: str | None = None) -> str:
    """
    Direct conversational AI Tutor chat powered by Gemini.
    First checks if a custom_api_key is provided from settings. If present, uses that key.
    Otherwise, checks and falls back to API_KEYS loaded from the .env file.
    """
    global _LAST_WORKING_KEY_INDEX, _LAST_WORKING_MODEL

    # 1. First check in settings: if custom_api_key is provided, use that key
    if custom_api_key and str(custom_api_key).strip():
        keys_to_try = [str(custom_api_key).strip()]
        print("[ai_tutor] chat_with_ai: Using API key from Settings (priority over .env).")
    else:
        # 2. Else check the API keys in the .env file
        raw_keys = list(API_KEYS)
        if len(raw_keys) > 1:
            idx = _LAST_WORKING_KEY_INDEX % len(raw_keys)
            keys_to_try = raw_keys[idx:] + raw_keys[:idx]
        else:
            keys_to_try = raw_keys
        print(f"[ai_tutor] chat_with_ai: Using {len(keys_to_try)} API key(s) from .env.")

    if not keys_to_try:
        return "Gemini API keys are not configured in Settings or ai_tutor_backend/.env."

    history = history or []
    history_lines = []
    for h in history[-4:]:
        role = "Student" if h.get("role") == "user" else "Tutor"
        history_lines.append(f"{role}: {h.get('text', '')}")
    history_str = "\n".join(history_lines) if history_lines else "None"

    prompt = f"""You are the AI Fault Analysis Tutor inside a Chaos Engineering learning tool (CD-SET).
You help students and developers understand software faults, root causes, recovery strategies, and resilience patterns.

CONTEXT:
Failure / Fault: {fault or "General Chaos Engineering / Software Resilience"}
Details / Evidence:
{context or "No specific execution trace provided."}

PRIOR CONVERSATION:
{history_str}

STUDENT QUESTION:
{question}

INSTRUCTIONS:
1. Answer the student's question clearly, practically, and educationally.
2. If asking about the error, why it failed, or how to fix it, reference the context, explain the root cause, and provide the concrete resilient code fix with line-by-line explanation.
3. Keep the tone encouraging, educational, and professional.
4. Reply directly in clear, clean markdown with syntax-highlighted code blocks where appropriate (no JSON wrapping).
"""

    models_to_try = list(CANDIDATE_MODELS)
    if _LAST_WORKING_MODEL in models_to_try:
        models_to_try.remove(_LAST_WORKING_MODEL)
        models_to_try.insert(0, _LAST_WORKING_MODEL)

    chat_config = types.GenerateContentConfig(
        max_output_tokens=1500,
        temperature=0.3,
    )

    for key_number, api_key in enumerate(keys_to_try, start=1):
        for model_name in models_to_try:
            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(
                        timeout=GEMINI_TIMEOUT * 1000
                    ),
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=chat_config,
                )
                if response.text and response.text.strip():
                    _LAST_WORKING_MODEL = model_name
                    if api_key in API_KEYS:
                        _LAST_WORKING_KEY_INDEX = API_KEYS.index(api_key)
                    return response.text.strip()
            except Exception as e:
                print(f"[ai_tutor] chat_with_ai key attempt ({model_name}) error: {e}")
                continue

    return "I am currently unable to reach the AI model. Please verify your Gemini API key and internet connectivity."