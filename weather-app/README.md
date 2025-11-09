# CosmoWeather — Upgraded Weather app (FastAPI + Static frontend)

Upgrades included:
- Weather icons and friendly descriptions (mapped from Open-Meteo weather codes).
- Autocomplete endpoint (`/api/autocomplete`) and frontend suggestions.
- Improved UI with animations, unit toggle (°C / °F), and cleaner layout.
- Simple in-memory TTL cache in the backend (5 minute TTL) to reduce upstream calls.
- Automated tests (pytest) for smoke-testing API endpoints.
- Rebuilt project ZIP with all files.

Notes:
- The cache is in-memory and per-process. Serverless platforms do not guarantee persistence across invocations, but this helps while the instance is warm.
- Tests attempt to call real upstream APIs via the FastAPI app; running them locally requires internet access.