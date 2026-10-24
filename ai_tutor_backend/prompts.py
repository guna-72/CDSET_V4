def create_prompt(fault_data):

    fault = fault_data.get("fault", "UNKNOWN")
    service = fault_data.get("service", "Unknown Service")
    endpoint = fault_data.get("endpoint", "Not specified")
    error_message = fault_data.get("error_message", "Not specified")
    file = fault_data.get("file", "Not specified")
    line = fault_data.get("line", "Not specified")
    current_code = fault_data.get("current_code", "")
    details = fault_data.get("details", "No additional details")
    timestamp = fault_data.get("timestamp", "Not available")

    if not current_code:
        current_code = "No source code was provided."

    return f"""
You are an AI Fault Analysis Tutor in a Chaos Engineering project.

A real application fault has been detected.

FAULT INFORMATION
-----------------

Fault Type:
{fault}

Service:
{service}

Endpoint:
{endpoint}

Error Message:
{error_message}

File:
{file}

Line:
{line}

Current / Problematic Code:
{current_code}

Additional Details:
{details}

Timestamp:
{timestamp}


YOUR TASK
---------

Analyze the supplied fault and identify the actual problem.

CRITICAL INSTRUCTIONS FOR SOLVED CODE:
1. Do NOT merely wrap the code in a generic `try...except` or `try...catch` block. Catching exceptions blindly without fixing the root cause does NOT solve the actual problem and will be rejected.
2. Provide the ACTUAL, REAL resilient implementation that solves the underlying defect:
   - For Malformed JSON / Empty Input / Invalid Content-Type / Null Body:
     Validate headers (e.g. Content-Type: application/json), check that the body exists and is not empty before parsing, validate schema and required fields, and explicitly return a clean HTTP 400 (or 415/422) with a helpful error message.
   - For Boundary Input / Unexpected Types:
     Add input schema validation, type checks, range/length constraints, sanitization, and return clean HTTP 400.
   - For API Timeout / Slow Response:
     Set explicit request/connection timeouts (e.g., timeout=3.0s or AbortSignal.timeout(3000)), add retry with exponential backoff, and return a clean fallback or 504 error.
   - For Database Connection Failure / Connection Refused:
     Add connection retry logic, verify pool health, and return a clean HTTP 503 Service Unavailable instead of crashing.
   - For Missing Environment Variables:
     Use `os.getenv('VAR', default)` with sensible fallbacks or perform fail-fast validation at startup with a clear error message.
   - For Missing Files / Permission Denied:
     Verify file existence (`os.path.exists`) and readability, provide fallback defaults or clean configuration error.
   - For Oversized Payloads:
     Verify Content-Length header against max allowed size (e.g. 1MB) before reading body, returning HTTP 413 Payload Too Large.
   - For Request Bursts / Concurrency:
     Use rate limiting, concurrency semaphores, or multithreaded server handling returning HTTP 429.
3. The `replacement_code` must be clean, syntactically correct, ready-to-use drop-in replacement code matching the language of the original code. Do NOT wrap `replacement_code` in markdown backticks inside the JSON string.
4. Use ONLY the information supplied above. Do NOT invent unrelated files or functions.
5. In `why_replacement_works`, clearly explain how this specific solved code fixes the actual issue without just suppressing errors.
6. In `why_it_failed`, explain the exact technical reason the original code failed under this chaos condition.
7. Give clear, actionable `recovery_steps` and `prevention` guidance.

Return ONLY valid JSON.

Use exactly these fields:

{{
    "fault": "",
    "severity": "",
    "error_location": "",
    "problem": "",
    "problematic_code": "",
    "why_it_failed": "",
    "replacement_code": "",
    "why_replacement_works": "",
    "recovery_steps": [],
    "prevention": ""
}}

Fault-specific guidance:

API_TIMEOUT / SLOW_RESPONSE:
Explain timeout handling, retry logic with backoff, and fallback responses.

DATABASE_CONNECTION_FAILURE / CONNECTION_REFUSED:
Explain database connection failure, reconnect retries, and HTTP 503 handling.

HTTP_429 / REQUEST_BURST:
Explain rate limiting, concurrency bounding, and retry-after headers.

HTTP_500 / CRASH:
Explain root cause defect and proper exception prevention.

MALFORMED_JSON / INVALID_INPUT / EMPTY_INPUT:
Explain input validation, Content-Type enforcement, payload schema validation, and HTTP 400 error responses (not just generic try/except).

CONNECTION_DROP:
Explain connection loss, reconnection, and idempotent retry.

SERVICE_UNAVAILABLE:
Explain service health checking, graceful degradation, and safe fallback.

AUTHENTICATION_FAILURE:
Explain token extraction, Bearer header validation, and clean 401 handling.

Always return valid JSON.
"""