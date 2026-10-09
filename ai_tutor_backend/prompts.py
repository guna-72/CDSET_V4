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

IMPORTANT RULES:

1. Use ONLY the information supplied above.
2. Do NOT invent a file name, line number, or source code.
3. If file or line information is supplied, mention it exactly.
4. If current code is supplied, analyze that code specifically.
5. If current code is missing, clearly say that exact code replacement cannot be determined.
6. Give a practical replacement code when enough information is available.
7. Keep the explanation simple and suitable for a diploma project demonstration.
8. Explain why the original code failed.
9. Explain why the replacement code solves the problem.
10. Give clear recovery steps.
11. Give prevention suggestions.

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

API_TIMEOUT:
Explain timeout handling, retry logic and exponential backoff.

DATABASE_CONNECTION_FAILURE:
Explain database connection failure, connection pooling and reconnect handling.

HTTP_429:
Explain rate limiting and retry with backoff.

HTTP_500:
Explain server-side failure and safe retry.

MALFORMED_JSON:
Explain JSON parsing and input validation.

CONNECTION_DROP:
Explain connection loss and reconnect/retry handling.

SERVICE_UNAVAILABLE:
Explain unavailable service and safe retry/fallback.

AUTHENTICATION_FAILURE:
Explain invalid, missing or expired authentication credentials.

Always return valid JSON.
"""