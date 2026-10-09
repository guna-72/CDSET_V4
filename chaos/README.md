# Chaos Tutor / CD-SET — Frontend

This is the original React/Vite frontend visual design for Chaos Tutor. The UI has been kept intact while its data/actions are connected to the real Chaos Tutor backend.

## Real backend workflow

The integrated UI can use the backend for:

- Project ZIP upload
- Project analysis
- Failure-point discovery
- Experiment generation
- Experiment execution
- Run logs
- Diagnosis
- Tutor sessions and answer evaluation
- Coverage
- Project reports

The original page presentation, navigation, styling, and components remain the frontend source of truth.

## Start

Start the backend first:

```bash
cd ../backend
python -m unittest discover -s tests -p "test_*.py"
python -m app.main
```

Backend: `http://127.0.0.1:8090`

Then start the frontend:

```bash
cd ../chaos
npm install
npm run dev
```

Frontend: `http://localhost:5173`

The frontend API base defaults to `http://127.0.0.1:8090` and can be overridden with `VITE_API_URL`.

## Stack

- React 18
- Vite
- Lucide React
- Motion/OGL where used by the original UI
- Custom Python HTTP backend (standard library core)
- SQLite persistence
- Optional LLM diagnosis providers with API-key rotation/failover
