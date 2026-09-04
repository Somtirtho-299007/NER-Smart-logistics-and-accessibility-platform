# NER Smart Logistics — Clean Ready Build

## Files
- `index.html` — frontend. This is the file the static site should publish.
- `main.py` — FastAPI backend with authentication, shipments, driver assignment/GPS, route intelligence, Open-Meteo weather, and NASA EONET event data.
- `models.py` — SQLAlchemy database models.
- `database.py` — SQLite fallback + PostgreSQL/Render DATABASE_URL support.
- `requirements.txt` — Python dependencies.
- `render.yaml` — optional Render Blueprint for the backend and static frontend.

## Render backend
Use a Python web service with:
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Environment variable: `DATABASE_URL` = your Render PostgreSQL connection string.

## Render frontend
Use a Static Site publishing the repository root. The entry file is `index.html`.

The frontend is configured to call:
`https://ner-smart-logistics-and-accessibility.onrender.com`

## Important
Do not use `index (4).html`. The clean build intentionally uses `index.html` so a normal static-site deployment has an unambiguous entry point.
