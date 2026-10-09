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

# Models to try in order of speed and availability
_preferred = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
_raw_models = [
    _preferred,
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
]
CANDIDATE_MODELS = []
for _m in _raw_models:
    if _m and _m not in CANDIDATE_MODELS:
        CANDIDATE_MODELS.append(_m)

# Request timeout in seconds for each Gemini API call
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "12"))


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

def generate_ai_response(fault_data):
    """
    Send fault_data to Gemini and return a structured analysis dict.
    Tries each configured API key in order until one succeeds.
    Returns a graceful fallback response if all keys fail or none exist.
    """

    # No API keys configured
    if not API_KEYS:
        print("[ai_tutor] No Gemini API keys configured — returning fallback.")
        return _no_keys_response(fault_data)

    prompt = create_prompt(fault_data)

    # Try each API key in rotation
    for key_number, api_key in enumerate(API_KEYS, start=1):
        try:
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=GEMINI_TIMEOUT * 1000  # milliseconds
                ),
            )

            response = None
            used_model = None
            for m in CANDIDATE_MODELS:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=prompt,
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

            print(
                f"[ai_tutor] Gemini API key {key_number} succeeded "
                f"(model={used_model})."
            )

            return result

        except Exception as error:
            print(
                f"[ai_tutor] Gemini API key {key_number} failed: {error}"
            )
            continue

    # All keys failed
    print("[ai_tutor] All Gemini API keys failed — returning fallback.")
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

def chat_with_ai(question: str, fault: str = "", context: str = "", history: list | None = None) -> str:
    """
    Direct conversational AI Tutor chat powered by Gemini.
    Answers any user query, drawing from fault context and conversation history.
    """
    if not API_KEYS:
        return "Gemini API keys are not configured in ai_tutor_backend/.env."

    history = history or []
    history_lines = []
    for h in history[-6:]:
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
1. Answer the student's question clearly, practically, and concisely.
2. If asking about the error, why it failed, or how to fix it, reference the context and provide a clear explanation with code if needed.
3. Keep the tone encouraging, educational, and professional.
4. Reply directly in clear, clean text or markdown (no JSON wrapping).
"""

    for key_number, api_key in enumerate(API_KEYS, start=1):
        for model_name in CANDIDATE_MODELS:
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
                )
                if response.text and response.text.strip():
                    return response.text.strip()
            except Exception as e:
                print(f"[ai_tutor] chat_with_ai key {key_number} ({model_name}) error: {e}")
                continue

    return "I am currently unable to reach the AI model. Please verify your Gemini API key and internet connectivity."