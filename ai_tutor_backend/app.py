import os
from flask import Flask, request, jsonify
from flask_cors import CORS

from ai_tutor import generate_ai_response, chat_with_ai


app = Flask(__name__)

# ------------------------------------------------
# CORS — allow frontend origins
# ------------------------------------------------

ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "http://127.0.0.1:5173")

CORS(app, origins=[
    ALLOWED_ORIGIN,
    "http://localhost:5173",    # Vite dev server (localhost variant)
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",   # Vite alt port
    "http://localhost:5174",
    "http://127.0.0.1:8090",
    "http://localhost:8090",
])


# ------------------------------------------------
# HOME
# ------------------------------------------------

@app.route("/")
def home():
    return jsonify({
        "status": "AI Tutor Backend Running",
        "module": "AI Fault Analysis",
        "endpoint": "/api/ai-tutor",
        "chat_endpoint": "/api/chat",
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    })


# ------------------------------------------------
# HEALTH CHECK
# ------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "OK",
        "service": "AI Tutor"
    })


# ------------------------------------------------
# AI TUTOR CHAT
# ------------------------------------------------

@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(force=True, silent=True) or {}
        question = data.get("question") or data.get("message") or ""
        if not question or not str(question).strip():
            return jsonify({
                "error": "Question is required."
            }), 400

        fault = data.get("fault", "")
        context = data.get("context", "")
        history = data.get("history", [])

        # Priority: first check setting / request key; if present, use it; else fallback to .env in ai_tutor.py
        custom_key = data.get("api_key") or data.get("apiKey") or request.headers.get("X-API-Key")
        if custom_key and str(custom_key).strip():
            custom_key = str(custom_key).strip()
        else:
            custom_key = None

        print("\n================================")
        print("AI TUTOR CHAT RECEIVED")
        print("================================")
        print("Question:   ", question)
        print("Fault:      ", fault)
        print("Key Source: ", "Settings (request body/header)" if custom_key else "Backend .env fallback")
        print("================================\n")

        reply = chat_with_ai(
            question=str(question).strip(),
            fault=str(fault),
            context=str(context) if isinstance(context, str) else str(context),
            history=history if isinstance(history, list) else [],
            custom_api_key=custom_key,
        )
        return jsonify({
            "answer": reply,
            "status": "success",
            "source": "settings" if custom_key else "env"
        }), 200

    except Exception as error:
        print("[ai_tutor] Unhandled error in /api/chat:", error)
        return jsonify({"error": str(error)}), 500


# ------------------------------------------------
# AI TUTOR FAULT ANALYSIS
# ------------------------------------------------

@app.route("/api/ai-tutor", methods=["POST"])
def ai_tutor():
    try:
        fault_data = request.get_json(force=True, silent=True)
        if not fault_data:
            return jsonify({
                "error": "No fault information received. Send a JSON body with at least a 'fault' field."
            }), 400

        fault = fault_data.get("fault")
        if not fault or not str(fault).strip():
            return jsonify({
                "error": "Fault type is required."
            }), 400

        # Priority: first check setting / request key; if present, use it; else fallback to .env in ai_tutor.py
        custom_key = fault_data.get("api_key") or fault_data.get("apiKey") or request.headers.get("X-API-Key")
        if custom_key and str(custom_key).strip():
            custom_key = str(custom_key).strip()
        else:
            custom_key = None

        print("\n================================")
        print("AI TUTOR FAULT RECEIVED")
        print("================================")
        print("Fault:      ", fault)
        print("Error:      ", fault_data.get("error_message"))
        print("Service:    ", fault_data.get("service"))
        print("File:       ", fault_data.get("file"))
        print("Line:       ", fault_data.get("line"))
        print("Key Source: ", "Settings (request body/header)" if custom_key else "Backend .env fallback")
        print("================================\n")

        result = generate_ai_response(fault_data, custom_api_key=custom_key)
        return jsonify(result), 200

    except Exception as error:
        print("[ai_tutor] Unhandled error in /api/ai-tutor:", error)
        return jsonify({"error": str(error)}), 500


# ------------------------------------------------
# TEST FAULT
# ------------------------------------------------

@app.route("/api/test-fault", methods=["POST"])
def test_fault():
    test_fault_data = {
        "fault": "AUTHENTICATION_FAILURE",
        "service": "Authentication Service",
        "endpoint": "/api/login",
        "error_message": "401 Unauthorized",
        "file": "auth.py",
        "line": 42,
        "current_code": "token = request.headers.get('token')",
        "details": "Authentication token was rejected.",
        "timestamp": "2026-09-23 14:00:00"
    }
    result = generate_ai_response(test_fault_data)
    return jsonify(result), 200


# ------------------------------------------------
# START SERVER
# ------------------------------------------------

if __name__ == "__main__":
    # This is a purely local, single-user helper service for the main
    # backend and the frontend running on the same machine (see
    # app/tutor.py's HTTP call to 127.0.0.1:5000). The rest of this
    # project deliberately binds loopback-only and goes out of its way to
    # avoid host networking (see backend/app/sandbox.py) - this service
    # previously didn't follow that: host="0.0.0.0" put it on every
    # network interface (confirmed live: reachable at this machine's real
    # LAN address, not just 127.0.0.1), and debug=True left Werkzeug's
    # interactive debugger active on top of that. On a shared/public
    # network, that's a real attack surface for a tool that otherwise has
    # none. Default to loopback + debug off; opt back into either only
    # for actual local development.
    host = os.getenv("AI_TUTOR_HOST", "127.0.0.1")
    debug = os.getenv("AI_TUTOR_DEBUG", "false").strip().lower() in ("1", "true", "yes")
    app.run(
        host=host,
        port=int(os.getenv("AI_TUTOR_PORT", "5000")),
        debug=debug,
    )
