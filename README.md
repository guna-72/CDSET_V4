# Chaos Tutor / CD-SET (Chaos Engineering Diagnostic & Software Education Toolkit)

Chaos Tutor (CD-SET) is an automated resilience and chaos engineering diagnostic platform with an AI-assisted interactive tutoring engine. It uploads project archives, discovers failure surfaces via static analysis, safely executes sandboxed chaos experiments, diagnoses failures, and guides developers through interactive resilience learning.

---

## 🏗️ Architecture

The project consists of three core components:

1. **Frontend (`/chaos`)**
   - React 18 + Vite modern interactive interface
   - Real-time project upload, pipeline orchestration, experiment runner, and diagnostic reports
   - Interactive Tutor view with quiz assessment, concept breakdown, and PDF export

2. **Core Backend (`/backend`)**
   - Python-based server with stdlib-only core architecture (zero heavy dependencies required for core execution)
   - AST-based static analyzer for route, database, file, and network surface detection
   - Sandboxed execution harness with process grouping, timeout termination, and network isolation
   - Rule-based & multi-provider LLM failover diagnoser (Gemini, Groq, OpenAI, Anthropic, DeepSeek, OpenRouter)
   - SQLite persistence layer for projects, runs, and failure metrics

3. **AI Tutor Backend (`/ai_tutor_backend`)**
   - Dedicated lightweight Flask microservice powering conversational AI tutor guidance
   - Google Gemini API integration with automatic key rotation and failover
   - Provides personalized explanations, resilience hints, and answers to student questions

---

## 🚀 Quick Start (Windows)

### Option 1: One-Click Launchers (Recommended)
- **`Start ChaosTutor.vbs`** or **`start_windows.bat`**: Starts all services (Backend, Frontend, and AI Tutor) quietly in the background and opens the application in your browser.
- **`Start ChaosTutor Network.vbs`** or **`start_network.bat`**: Starts the application bound to your local network IP for multi-device access.
- **`Stop ChaosTutor.vbs`**: Gracefully stops all running Chaos Tutor background processes.

---

### Option 2: Manual Setup & Execution

#### 1. Core Backend
```bash
cd backend
# Optional: create and activate a virtual environment
python -m venv venv
venv\Scripts\activate

# Install optional dependencies (e.g., pytest, firebase-admin)
pip install -r requirements.txt

# Run backend test suite
python -m unittest discover -s tests -p "test_*.py"

# Start the backend server (runs on http://127.0.0.1:8090)
python -m app.main
```

#### 2. AI Tutor Backend
```bash
cd ai_tutor_backend
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env   # Add your Gemini API key in .env

# Start AI Tutor backend (runs on http://127.0.0.1:5005)
python app.py
```

#### 3. Frontend
```bash
cd chaos
npm install
cp .env.example .env   # Configure API URL (defaults to http://127.0.0.1:8090)

# Start Vite development server (runs on http://localhost:5173)
npm run dev
```

---

## ⚙️ Configuration & Environment Variables

Templates are provided across each service:
- `backend/.env.example` -> `backend/.env` (LLM diagnosis keys, sandbox flags, optional auth token)
- `ai_tutor_backend/.env.example` -> `ai_tutor_backend/.env` (Gemini API keys for AI tutoring)
- `chaos/.env.example` -> `chaos/.env` (Frontend API endpoint and optional Firebase config)

> **Note:** Never commit active API keys or private credentials to git. Keep your `.env` files untracked.

---

## 🧪 Testing

- **Backend tests:**
  ```bash
  cd backend
  python -m unittest discover -s tests -p "test_*.py" -v
  ```
- **Frontend UI tests:**
  ```bash
  cd chaos
  npm run test:ui
  ```

---

## 📜 License & Notes
Designed for chaos engineering resilience testing, diagnostics, and hands-on developer training.
