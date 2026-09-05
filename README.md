# NER Smart Logistics

Adaptive, disruption-aware logistics platform for the North-East India / Himalayan corridor.

Deploy backend with: `uvicorn main:app --host 0.0.0.0 --port $PORT`
Serve `index.html` as the frontend entry file (static hosting — it talks to the API by absolute URL).

## What changed in this pass

**Root cause fixes**
- Same shipment ID across different accounts previously failed. Cause: `shipment_id` was globally unique in the database AND nearly every backend query filtered by `shipment_id` alone, ignoring the owner. Fixed with a composite `(owner_username, shipment_id)` constraint and a single shared lookup function (`resolve_shipment_for_caller` in `main.py`) used by every shipment-scoped endpoint, so isolation logic isn't duplicated (and can't drift out of sync) across routes.
- Route Intelligence and AI Disruption Analysis returned "Failed to fetch". Cause: the code called a function `geocode_location(...)` that was never defined anywhere (only `geocode_place` existed) — an unhandled `NameError` on every call. Fixed by defining `geocode_location`.
- `GET /shipments/{id}` (single) and `POST /shipments/{id}/assign-driver` had no authentication check at all. Fixed.
- `DriverAssignmentDB.shipment_id` was also globally unique, which would have broken driver assignment as soon as two owners shared a visible shipment ID. Fixed — assignments now key off the shipment's internal database ID.

**Architecture change (as requested)**
All relationship tables — driver assignments, GPS history, tracking events, incident reports — now reference the shipment's internal auto-increment `id` (`shipment_db_id`) rather than the visible `shipment_id` string, so two owners' shipments sharing a visible ID can never have their GPS/tracking/assignment data mixed up.

**New features**
- Driver incident reporting (`POST /incidents`, `GET /shipments/{id}/incidents`): flood / landslide / road blockage / accident / other, with severity and location.
- Adaptive disruption scoring replaces the previous approach (IsolationForest trained on only 2-3 route alternatives, which isn't a meaningful sample). The new layer is a transparent, explainable weighted score over real stored incident reports — severity-weighted, recency-decayed (12h half-life, 72h expiry), and proximity-weighted against the actual route geometry (not just 3 sample points) within the existing 50 km corridor rule. Every score comes with a plain-language "why" list.
- Recheck Route (`GET /shipments/{id}/recheck-route`): re-runs route intelligence starting from the driver's latest GPS position instead of the shipment's original origin, and returns a stay/change decision with a reason.
- Modern responsive dashboard UI (dark control-room theme), including a visual step-by-step route path display.

**Preserved**
Registration/login (user + driver), shipment create/edit/delete, driver assignment, GPS tracking, tracking history, shipment-condition risk, NASA/Open-Meteo/OSRM integrations, and the Render deployment shape — none of this was rewritten from scratch, only the isolation and lookup logic underneath it.

## Files
- `main.py` — FastAPI backend
- `models.py` — SQLAlchemy models
- `database.py` — DB engine/session setup (unchanged)
- `index.html` — frontend (dealer + driver dashboards)
- `requirements.txt` — Python dependencies
- `render.yaml` — Render deployment config (unchanged)

## Notes for a fresh deploy
Because the shipment uniqueness rule changed from a single-column constraint to a composite one, this needs a fresh schema (SQLAlchemy's `create_all` won't alter an existing table's constraints). If you're pointing at a database that already has the old schema, drop and recreate the `shipments` and `driver_assignments` tables (or point at a new Postgres instance) before deploying.
