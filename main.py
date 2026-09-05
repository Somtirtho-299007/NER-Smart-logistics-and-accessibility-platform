from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_
import urllib.parse
import urllib.request
import json
import hashlib
import secrets
import math
from datetime import datetime, timedelta

from database import SessionLocal, engine, Base
from models import (
    ShipmentDB,
    TrackingEventDB,
    UserDB,
    DriverAssignmentDB,
    GPSLocationDB,
    DriverDB,
    IncidentDB,
)

from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# FASTAPI
# ---------------------------------------------------------

app = FastAPI(
    title="NER Smart Logistics Intelligence API",
    description="Adaptive, disruption-aware logistics platform for the North Eastern Region"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# ---------------------------------------------------------
# SIMPLE PROTOTYPE SESSION STORAGE
# (kept in-memory, matching original architecture — a restart clears
#  sessions, which is fine for this prototype and unrelated to the bugs
#  being fixed)
# ---------------------------------------------------------

sessions = {}
active_driver_tokens = {}


# ---------------------------------------------------------
# PYDANTIC MODELS
# ---------------------------------------------------------

class DriverLogin(BaseModel):
    driver_id: str
    password: str


class DriverGPS(BaseModel):
    driver_id: str
    latitude: float
    longitude: float


class ShipmentUpdate(BaseModel):
    origin: str | None = None
    destination: str | None = None
    weight: float | None = None
    cargo: str | None = None
    status: str | None = None


class Shipment(BaseModel):
    shipment_id: str
    origin: str
    destination: str
    weight: float
    cargo: str
    status: str = "pending"


class LoginRequest(BaseModel):
    username: str
    password: str


class AssignmentRequest(BaseModel):
    driver_id: str


class GPSRequest(BaseModel):
    shipment_id: str
    latitude: float
    longitude: float
    accuracy: float | None = None


class IncidentReport(BaseModel):
    shipment_id: str | None = None
    incident_type: str  # flood | landslide | road_blockage | accident | other
    severity: str  # low | medium | high | critical
    latitude: float
    longitude: float
    road_name: str | None = None
    description: str | None = None


# ---------------------------------------------------------
# DATABASE DEPENDENCY
# ---------------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------
# PASSWORD / TOKEN HELPERS
# ---------------------------------------------------------

def hash_password(password: str):
    return hashlib.sha256(password.encode()).hexdigest()


def create_driver_token(driver_id: str):
    token = secrets.token_hex(16)
    expiration = datetime.utcnow() + timedelta(hours=1)
    active_driver_tokens[token] = {
        "driver_id": driver_id,
        "expires_at": expiration
    }
    return token


def get_driver_from_token(token: str):
    session = active_driver_tokens.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if datetime.utcnow() > session["expires_at"]:
        del active_driver_tokens[token]
        raise HTTPException(status_code=401, detail="Session expired")
    return session["driver_id"]


def get_current_user(token: str):
    if token not in sessions:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return sessions[token]


def get_bearer_token(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    return authorization.replace("Bearer ", "").strip()


def resolve_caller(authorization: str | None, db: Session):
    """
    Returns a dict: {"role": "driver"|"dealer", "username": <driver_id or username>}
    Works for both driver-token and dealer/user-session callers.
    """
    token = get_bearer_token(authorization)
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        return {"role": "driver", "username": driver_id}
    user = get_current_user(token)
    return {"role": user.get("role", "dealer"), "username": user["username"]}


# ---------------------------------------------------------
# SHIPMENT LOOKUP HELPERS (ACCOUNT ISOLATION CORE)
# ---------------------------------------------------------
# All shipment access must be scoped by BOTH the visible shipment_id AND
# the identity of the caller (owner for dealers, assignment for drivers).
# The visible shipment_id is only unique per-owner, so filtering on it
# alone would leak/collide across accounts.

def get_owned_shipment(db: Session, shipment_id: str, owner_username: str) -> ShipmentDB | None:
    return db.query(ShipmentDB).filter(
        ShipmentDB.shipment_id == shipment_id,
        ShipmentDB.owner_username == owner_username
    ).first()


def get_shipment_for_driver(db: Session, shipment_id: str, driver_id: str) -> ShipmentDB | None:
    """
    A driver may only be assigned to ONE shipment (business rule preserved
    from the original prototype), so there's exactly one shipment (across
    all owners) reachable by a given driver for a given visible
    shipment_id: the one they're assigned to, if its visible ID matches.
    """
    assignment = db.query(DriverAssignmentDB).filter(
        DriverAssignmentDB.driver_username == driver_id
    ).first()
    if not assignment:
        return None
    shipment = db.query(ShipmentDB).filter(ShipmentDB.id == assignment.shipment_db_id).first()
    if not shipment or shipment.shipment_id != shipment_id:
        return None
    return shipment


def resolve_shipment_for_caller(db: Session, shipment_id: str, caller: dict) -> ShipmentDB:
    """
    Resolves a visible shipment_id to the correct internal ShipmentDB row
    for the calling identity, enforcing account isolation. Raises 404/403
    as appropriate. This is the single choke point used by every
    shipment-scoped endpoint so isolation logic lives in one place.
    """
    if caller["role"] == "driver":
        shipment = get_shipment_for_driver(db, shipment_id, caller["username"])
        if not shipment:
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
        return shipment
    shipment = get_owned_shipment(db, shipment_id, caller["username"])
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


def get_assignment_for_shipment_db_id(db: Session, shipment_db_id: int) -> DriverAssignmentDB | None:
    return db.query(DriverAssignmentDB).filter(
        DriverAssignmentDB.shipment_db_id == shipment_db_id
    ).first()


# ---------------------------------------------------------
# CREATE DEMO USERS
# ---------------------------------------------------------

def create_demo_users():
    db = SessionLocal()
    try:
        dealer = db.query(UserDB).filter(UserDB.username == "dealer1").first()
        if not dealer:
            db.add(UserDB(username="dealer1", password=hash_password("dealer123"), role="dealer"))

        driver = db.query(DriverDB).filter(DriverDB.driver_id == "driver1").first()
        if not driver:
            db.add(DriverDB(driver_id="driver1", password=hash_password("driver123")))

        db.commit()
    finally:
        db.close()


create_demo_users()


# ---------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------

@app.post("/driver/register")
def driver_register(data: DriverLogin, db: Session = Depends(get_db)):
    existing_driver = db.query(DriverDB).filter(DriverDB.driver_id == data.driver_id).first()
    if existing_driver:
        raise HTTPException(status_code=400, detail="Driver ID already exists")

    new_driver = DriverDB(driver_id=data.driver_id, password=hash_password(data.password))
    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)

    return {"message": "Driver registered successfully", "driver_id": new_driver.driver_id}


@app.post("/driver/login")
def driver_login(data: DriverLogin, db: Session = Depends(get_db)):
    driver = db.query(DriverDB).filter(DriverDB.driver_id == data.driver_id).first()
    if not driver or driver.password != hash_password(data.password):
        raise HTTPException(status_code=401, detail="Invalid driver ID or password")

    token = create_driver_token(driver.driver_id)
    return {"message": "Login successful", "token": token, "driver_id": driver.driver_id}


@app.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == data.username).first()
    if not user or user.password != hash_password(data.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = secrets.token_hex(16)
    sessions[token] = {"username": user.username, "role": user.role}

    return {"message": "Login successful", "token": token, "username": user.username, "role": user.role}


@app.post("/register")
def register_user(data: LoginRequest, db: Session = Depends(get_db)):
    existing_user = db.query(UserDB).filter(UserDB.username == data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = UserDB(username=data.username, password=hash_password(data.password), role="dealer")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "User registered successfully", "username": new_user.username, "role": new_user.role}


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@app.get("/")
def home():
    return {"message": "NER Smart Logistics API is running!"}


# =========================================================
# SHIPMENTS
# =========================================================

def serialize_shipment(shipment: ShipmentDB, driver_id: str | None):
    return {
        "shipment_id": shipment.shipment_id,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "weight": shipment.weight,
        "cargo": shipment.cargo,
        "status": shipment.status,
        "owner_username": shipment.owner_username,
        "driver_id": driver_id,
    }


@app.post("/shipments/")
def create_shipment(
    shipment: Shipment,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    token = get_bearer_token(authorization)
    current_user = get_current_user(token)
    if current_user.get("role") == "driver":
        raise HTTPException(status_code=403, detail="Driver login required a dealer account to create shipments")

    if not shipment.shipment_id.strip():
        raise HTTPException(status_code=400, detail="Shipment ID is required")
    if not shipment.origin.strip() or not shipment.destination.strip():
        raise HTTPException(status_code=400, detail="Origin and destination are required")
    if shipment.weight is None or shipment.weight <= 0:
        raise HTTPException(status_code=400, detail="Weight must be a positive number")

    # Uniqueness is scoped to the current owner only — a different owner
    # may use the same visible shipment_id without conflict.
    existing = get_owned_shipment(db, shipment.shipment_id, current_user["username"])
    if existing:
        raise HTTPException(status_code=400, detail="You already have a shipment with this ID")

    new_shipment = ShipmentDB(
        shipment_id=shipment.shipment_id,
        origin=shipment.origin,
        destination=shipment.destination,
        weight=shipment.weight,
        cargo=shipment.cargo,
        status=shipment.status,
        owner_username=current_user["username"]
    )
    db.add(new_shipment)
    db.commit()
    db.refresh(new_shipment)

    return {"message": "Shipment created successfully", "shipment": serialize_shipment(new_shipment, None)}


@app.get("/shipments/")
def get_shipments(db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    caller = resolve_caller(authorization, db)

    if caller["role"] == "driver":
        assignment = db.query(DriverAssignmentDB).filter(
            DriverAssignmentDB.driver_username == caller["username"]
        ).first()
        shipments = []
        if assignment:
            shipment = db.query(ShipmentDB).filter(ShipmentDB.id == assignment.shipment_db_id).first()
            if shipment:
                shipments = [shipment]
    else:
        shipments = db.query(ShipmentDB).filter(ShipmentDB.owner_username == caller["username"]).all()

    result = []
    for s in shipments:
        assignment = get_assignment_for_shipment_db_id(db, s.id)
        result.append(serialize_shipment(s, assignment.driver_username if assignment else None))

    return {"shipments": result}


@app.get("/shipments/{shipment_id}")
def get_shipment(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)
    assignment = get_assignment_for_shipment_db_id(db, shipment.id)
    return {"shipment": serialize_shipment(shipment, assignment.driver_username if assignment else None)}


@app.put("/shipments/{shipment_id}")
def update_shipment(
    shipment_id: str,
    shipment: ShipmentUpdate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    existing_shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    if shipment.origin is not None:
        existing_shipment.origin = shipment.origin
    if shipment.destination is not None:
        existing_shipment.destination = shipment.destination
    if shipment.weight is not None:
        existing_shipment.weight = shipment.weight
    if shipment.cargo is not None:
        existing_shipment.cargo = shipment.cargo
    if shipment.status is not None:
        existing_shipment.status = shipment.status
        db.add(TrackingEventDB(
            shipment_db_id=existing_shipment.id,
            status=shipment.status,
            location=existing_shipment.destination
        ))

    db.commit()
    db.refresh(existing_shipment)
    assignment = get_assignment_for_shipment_db_id(db, existing_shipment.id)
    return {
        "message": "Shipment updated successfully",
        "shipment": serialize_shipment(existing_shipment, assignment.driver_username if assignment else None)
    }


@app.delete("/shipments/{shipment_id}")
def delete_shipment(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    token = get_bearer_token(authorization)
    if token in active_driver_tokens:
        raise HTTPException(status_code=403, detail="Drivers cannot delete shipments")

    current_user = get_current_user(token)
    existing_shipment = get_owned_shipment(db, shipment_id, current_user["username"])
    if not existing_shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    db.query(TrackingEventDB).filter(TrackingEventDB.shipment_db_id == existing_shipment.id).delete(synchronize_session=False)
    db.query(GPSLocationDB).filter(GPSLocationDB.shipment_db_id == existing_shipment.id).delete(synchronize_session=False)
    db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_db_id == existing_shipment.id).delete(synchronize_session=False)
    db.query(IncidentDB).filter(IncidentDB.shipment_db_id == existing_shipment.id).delete(synchronize_session=False)
    db.delete(existing_shipment)
    db.commit()

    return {"message": "Shipment deleted successfully"}


# =========================================================
# TRACKING
# =========================================================

@app.get("/shipments/{shipment_id}/tracking")
def get_tracking_history(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)
    events = db.query(TrackingEventDB).filter(
        TrackingEventDB.shipment_db_id == shipment.id
    ).order_by(TrackingEventDB.id.asc()).all()

    return {"tracking_history": [
        {"status": e.status, "location": e.location, "timestamp": e.timestamp}
        for e in events
    ]}


# =========================================================
# DRIVER ASSIGNMENT
# =========================================================

@app.post("/shipments/{shipment_id}/assign-driver")
def assign_driver(
    shipment_id: str,
    data: AssignmentRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    token = get_bearer_token(authorization)
    if token in active_driver_tokens:
        raise HTTPException(status_code=403, detail="Drivers cannot assign drivers")
    current_user = get_current_user(token)

    shipment = get_owned_shipment(db, shipment_id, current_user["username"])
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    driver = db.query(DriverDB).filter(DriverDB.driver_id == data.driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail=f"Driver {data.driver_id} not found")

    assignment = get_assignment_for_shipment_db_id(db, shipment.id)
    if assignment:
        raise HTTPException(status_code=400, detail="Shipment already has a driver assigned")

    occupied = db.query(DriverAssignmentDB).filter(
        DriverAssignmentDB.driver_username == data.driver_id
    ).first()
    if occupied:
        raise HTTPException(status_code=400, detail="Driver is already assigned to another shipment")

    assignment = DriverAssignmentDB(shipment_db_id=shipment.id, driver_username=data.driver_id)
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    return {"message": "Driver assigned successfully", "shipment_id": shipment_id, "driver_id": data.driver_id}


@app.get("/drivers")
def get_drivers(db: Session = Depends(get_db)):
    occupied = {x.driver_username for x in db.query(DriverAssignmentDB).all()}
    return {"drivers": [
        {"driver_id": d.driver_id}
        for d in db.query(DriverDB).all()
        if d.driver_id not in occupied
    ]}


@app.get("/available-shipments")
def get_available_shipments(db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    token = get_bearer_token(authorization)
    current_user = get_current_user(token)
    assigned_db_ids = {x.shipment_db_id for x in db.query(DriverAssignmentDB).all()}
    shipments = db.query(ShipmentDB).filter(ShipmentDB.owner_username == current_user["username"]).all()
    return {"shipments": [
        {"shipment_id": x.shipment_id, "origin": x.origin, "destination": x.destination, "status": x.status}
        for x in shipments
        if x.id not in assigned_db_ids
    ]}


# =========================================================
# DRIVER GPS
# =========================================================

@app.post("/driver/gps")
def update_driver_gps(
    gps: GPSRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    token = get_bearer_token(authorization)
    driver_id = get_driver_from_token(token)

    shipment = get_shipment_for_driver(db, gps.shipment_id, driver_id)
    if not shipment:
        raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")

    location = GPSLocationDB(
        driver_username=driver_id,
        shipment_db_id=shipment.id,
        latitude=gps.latitude,
        longitude=gps.longitude,
        accuracy=gps.accuracy
    )
    db.add(location)
    db.commit()
    db.refresh(location)

    return {
        "message": "GPS updated successfully",
        "driver_id": driver_id,
        "shipment_id": gps.shipment_id,
        "latitude": gps.latitude,
        "longitude": gps.longitude,
        "accuracy": gps.accuracy,
        "timestamp": location.timestamp
    }


@app.get("/shipments/{shipment_id}/location")
def get_driver_location(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    location = db.query(GPSLocationDB).filter(
        GPSLocationDB.shipment_db_id == shipment.id
    ).order_by(GPSLocationDB.id.desc()).first()

    if not location:
        return {"shipment_id": shipment_id, "message": "No GPS data available yet", "latitude": None, "longitude": None}

    return {
        "shipment_id": shipment_id,
        "driver_id": location.driver_username,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "accuracy": location.accuracy,
        "timestamp": location.timestamp
    }


# =========================================================
# INCIDENT / DISRUPTION REPORTING
# =========================================================

VALID_INCIDENT_TYPES = {"flood", "landslide", "road_blockage", "accident", "other"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@app.post("/incidents")
def report_incident(
    data: IncidentReport,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    token = get_bearer_token(authorization)
    driver_id = get_driver_from_token(token)

    incident_type = data.incident_type.strip().lower()
    severity = data.severity.strip().lower()
    if incident_type not in VALID_INCIDENT_TYPES:
        raise HTTPException(status_code=400, detail=f"incident_type must be one of {sorted(VALID_INCIDENT_TYPES)}")
    if severity not in VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {sorted(VALID_SEVERITIES)}")

    shipment_db_id = None
    if data.shipment_id:
        shipment = get_shipment_for_driver(db, data.shipment_id, driver_id)
        if not shipment:
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
        shipment_db_id = shipment.id

    incident = IncidentDB(
        shipment_db_id=shipment_db_id,
        reported_by=driver_id,
        incident_type=incident_type,
        severity=severity,
        latitude=data.latitude,
        longitude=data.longitude,
        road_name=data.road_name,
        description=data.description,
        active=True
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    return {
        "message": "Incident reported successfully",
        "incident_id": incident.id,
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "created_at": incident.created_at
    }


@app.get("/incidents/mine")
def get_my_incidents(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    """
    Incidents reported by the currently logged-in driver, so a driver can
    see and resolve their own reports directly (e.g. once a blockage they
    reported has cleared) without needing to know an internal incident ID.
    """
    token = get_bearer_token(authorization)
    driver_id = get_driver_from_token(token)

    incidents = db.query(IncidentDB).filter(
        IncidentDB.reported_by == driver_id
    ).order_by(IncidentDB.created_at.desc()).all()

    return {"incidents": [
        {
            "id": i.id,
            "incident_type": i.incident_type,
            "severity": i.severity,
            "latitude": i.latitude,
            "longitude": i.longitude,
            "road_name": i.road_name,
            "description": i.description,
            "active": i.active,
            "created_at": i.created_at
        } for i in incidents
    ]}


@app.get("/shipments/{shipment_id}/incidents")
def get_shipment_incidents(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    incidents = db.query(IncidentDB).filter(
        IncidentDB.shipment_db_id == shipment.id
    ).order_by(IncidentDB.created_at.desc()).all()

    return {"incidents": [
        {
            "id": i.id,
            "incident_type": i.incident_type,
            "severity": i.severity,
            "latitude": i.latitude,
            "longitude": i.longitude,
            "road_name": i.road_name,
            "description": i.description,
            "active": i.active,
            "created_at": i.created_at
        } for i in incidents
    ]}


@app.post("/incidents/{incident_id}/resolve")
def resolve_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    """
    Marks an incident as no longer active (e.g. blockage cleared, flood
    receded). Any logged-in driver or dealer can resolve an incident —
    this is a shared corridor signal, not owned by one account. Once
    inactive, it's immediately excluded from route/disruption scoring
    (active_incidents is always filtered by IncidentDB.active == True).
    """
    caller = resolve_caller(authorization, db)  # any authenticated user
    incident = db.query(IncidentDB).filter(IncidentDB.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.active = False
    db.commit()
    return {"message": "Incident marked resolved", "incident_id": incident_id}


# =========================================================
# GEOCODING
# =========================================================

geocode_cache = {}


def geocode_location(place):
    """
    Geocode a place name to coordinates via Nominatim.
    NOTE: this function was previously called as `geocode_location` from
    build_route_analysis() but only `geocode_place` existed anywhere in
    the codebase — that NameError is what surfaced to users as
    "Failed to fetch" on Route Intelligence and AI Disruption. Fixed by
    actually defining the function under the name that's called.
    """
    if place in geocode_cache:
        return geocode_cache[place]

    params = urllib.parse.urlencode({
        "q": place + ", India",
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "in"
    })
    url = "https://nominatim.openstreetmap.org/search?" + params
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NER-Smart-Logistics-Prototype/1.0"}
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not geocode '{place}': geocoding service unavailable ({str(e)})")

    if not data:
        raise HTTPException(status_code=400, detail=f"Could not geocode location: {place}")

    result = {
        "latitude": float(data[0]["lat"]),
        "longitude": float(data[0]["lon"]),
        "display_name": data[0]["display_name"]
    }
    geocode_cache[place] = result
    return result


# =========================================================
# WEATHER
# =========================================================

def get_weather(latitude, longitude):
    params = urllib.parse.urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "daily": "precipitation_sum,precipitation_probability_max,weather_code",
        "forecast_days": 1,
        "timezone": "auto"
    })
    url = "https://api.open-meteo.com/v1/forecast?" + params

    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.loads(response.read().decode())

    daily = data["daily"]
    return {
        "precipitation_mm": daily["precipitation_sum"][0],
        "rain_probability": daily["precipitation_probability_max"][0],
        "weather_code": daily["weather_code"][0]
    }


# =========================================================
# ROUTE SERVICE (OSRM)
# =========================================================

def get_routes(origin_lat, origin_lon, destination_lat, destination_lon):
    coordinates = f"{origin_lon},{origin_lat};{destination_lon},{destination_lat}"
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        + coordinates
        + "?alternatives=true&overview=full&steps=true&geometries=geojson"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "NER-Smart-Logistics-Prototype/1.0"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Routing service temporarily unavailable: {str(e)}")

    if data.get("code") != "Ok":
        raise HTTPException(status_code=400, detail=f"Routing service could not find a route: {data.get('code', 'unknown error')}")

    routes = data.get("routes")
    if not isinstance(routes, list):
        raise HTTPException(status_code=502, detail="Routing service returned an unexpected response format")
    if len(routes) == 0:
        raise HTTPException(status_code=404, detail="No routes found between these locations")

    return routes


# =========================================================
# ROUTE WEATHER SAMPLING
# =========================================================

def sample_route_weather(route, origin, destination):
    results = []
    for location in (origin, destination):
        try:
            weather = get_weather(location["latitude"], location["longitude"])
            results.append({
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "weather": weather
            })
        except Exception:
            continue
    return results


# =========================================================
# NASA HAZARD LAYER
# =========================================================

HAZARD_RADIUS_KM = 50.0
NASA_PMM_URL = "https://pmmpublisher.pps.eosdis.nasa.gov/opensearch"

hazard_cache = {}


def _bbox_around_point(lat, lon, radius_km=HAZARD_RADIUS_KM):
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / max(111.0 * math.cos(math.radians(lat)), 1.0)
    return lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _numeric_hazard_value(properties):
    if not isinstance(properties, dict):
        return None
    preferred = ["probability", "prob", "hazard", "value", "nowcast", "flood_probability", "landslide_probability", "risk"]
    for key in preferred:
        value = properties.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
    for key, value in properties.items():
        key_l = str(key).lower()
        if any(term in key_l for term in ("prob", "hazard", "nowcast", "risk")):
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                return float(value)
    return None


def _normalise_hazard_value(value):
    if value is None:
        return None
    if 0.0 <= value <= 1.0:
        return round(value * 100.0, 2)
    return round(max(0.0, min(100.0, value)), 2)


def get_nasa_hazard(lat, lon, dataset):
    """Fetch a real NASA PMM hazard product around a route point.
    Returns a source value normalized to 0-100 for display/risk scoring.
    No synthetic flood/landslide value is generated on failure.
    """
    date = datetime.utcnow().strftime("%Y-%m-%d")
    cache_key = (dataset, round(float(lat), 3), round(float(lon), 3), date)
    if cache_key in hazard_cache:
        return hazard_cache[cache_key]

    result = {
        "value": None,
        "source": "NASA GPM/PMM",
        "dataset": dataset,
        "radius_km": HAZARD_RADIUS_KM,
        "status": "Live hazard data unavailable"
    }
    try:
        query = urllib.parse.urlencode({"q": dataset, "limit": 1, "startTime": date, "endTime": date})
        request = urllib.request.Request(
            NASA_PMM_URL + "?" + query,
            headers={"User-Agent": "NER-Smart-Logistics-Prototype/1.0"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            catalog = json.loads(response.read().decode())
        items = catalog.get("items") or []
        if not items:
            hazard_cache[cache_key] = result
            return result

        item = items[0]
        subset_url = None
        for action in item.get("action", []):
            for using in action.get("using", []):
                if action.get("@type") == "ojo:subset" and using.get("url"):
                    subset_url = using["url"]
                    break
            if subset_url:
                break

        if not subset_url:
            result["status"] = "NASA product found, but spatial subset is unavailable"
            hazard_cache[cache_key] = result
            return result

        ll_lon, ll_lat, ur_lon, ur_lat = _bbox_around_point(lat, lon)
        url = subset_url.replace("{LLlon}", str(ll_lon)).replace("{LLlat}", str(ll_lat)) \
                         .replace("{URLon}", str(ur_lon)).replace("{URLat}", str(ur_lat))
        with urllib.request.urlopen(url, timeout=25) as response:
            payload = json.loads(response.read().decode())

        values = []
        for feature in payload.get("features", []) if isinstance(payload, dict) else []:
            value = _numeric_hazard_value(feature.get("properties", {}))
            if value is not None:
                values.append(value)
        if values:
            result["value"] = _normalise_hazard_value(max(values))
            result["status"] = "Live NASA hazard data"
        else:
            result["status"] = "NASA product returned no numeric hazard value for this area"
    except Exception as exc:
        result["status"] = f"NASA hazard feed unavailable: {str(exc)}"

    hazard_cache[cache_key] = result
    return result


def sample_route_hazards(route):
    geometry = route.get("geometry") or {}
    coordinates = geometry.get("coordinates", []) if isinstance(geometry, dict) else []
    if not coordinates:
        return {"flood": [], "landslide": []}
    indexes = list(dict.fromkeys([0, len(coordinates) // 2, len(coordinates) - 1]))
    flood, landslide = [], []
    for index in indexes:
        point = coordinates[index]
        if not isinstance(point, list) or len(point) < 2:
            continue
        lon, lat = float(point[0]), float(point[1])
        flood.append({"latitude": lat, "longitude": lon, "data": get_nasa_hazard(lat, lon, "flood_nowcast")})
        landslide.append({"latitude": lat, "longitude": lon, "data": get_nasa_hazard(lat, lon, "global_landslide_nowcast_30mn")})
    return {"flood": flood, "landslide": landslide}


# =========================================================
# ADAPTIVE INCIDENT-AWARE DISRUPTION SCORING
# =========================================================
# This replaces the old IsolationForest-on-2-3-routes approach, which does
# not represent meaningful learning (an anomaly-detection model needs a
# real population of prior observations, not the 2-3 alternatives for a
# single trip). Instead this uses a transparent, explainable weighted
# scoring layer over REAL stored incident reports:
#   - severity (critical/high/medium/low)
#   - recency (a report loses influence over time — half-life decay)
#   - proximity to the route corridor (near vs far, using the same
#     50 km rule as the NASA hazard sampling, but checked against the
#     full route geometry rather than 3 sample points, since incident
#     reports are sparse enough that this is cheap)
#   - repeated observations of the same kind of disruption reinforce the
#     score rather than being counted independently forever
#
# The result is a route-level "disruption score" with an explicit,
# itemised list of contributing reasons, so nothing is a black box.

SEVERITY_WEIGHT = {"low": 10, "medium": 25, "high": 45, "critical": 70}
INCIDENT_HALF_LIFE_HOURS = 12.0  # influence halves roughly every 12 hours
INCIDENT_EXPIRY_HOURS = 72.0     # incidents older than this are ignored entirely


def _incident_recency_factor(created_at: datetime) -> float:
    age_hours = max(0.0, (datetime.utcnow() - created_at).total_seconds() / 3600.0)
    if age_hours >= INCIDENT_EXPIRY_HOURS:
        return 0.0
    return 0.5 ** (age_hours / INCIDENT_HALF_LIFE_HOURS)


def _min_distance_to_route_km(lat, lon, route_coordinates, sample_every=3):
    if not route_coordinates:
        return None
    best = None
    for i in range(0, len(route_coordinates), max(1, sample_every)):
        point = route_coordinates[i]
        if not isinstance(point, list) or len(point) < 2:
            continue
        d = _haversine_km(lat, lon, float(point[1]), float(point[0]))
        if best is None or d < best:
            best = d
    return best


def score_incidents_near_route(route, incidents):
    """
    Returns (score_contribution, reasons, matched_incidents) for a single
    route, based on stored incident reports within HAZARD_RADIUS_KM of the
    route corridor.
    """
    geometry = route.get("geometry") or {}
    coordinates = geometry.get("coordinates", []) if isinstance(geometry, dict) else []

    if not coordinates:
        # Route geometry is missing/malformed (e.g. routing API returned an
        # unexpected shape). Fail loudly instead of silently scoring every
        # incident as "not near the route" — that failure mode is exactly
        # what previously made driver-reported incidents invisible to
        # route risk scoring even when they were right on the route.
        return 0.0, ["Route geometry unavailable — incident proximity could not be checked"], []

    matched = []
    for incident in incidents:
        recency = _incident_recency_factor(incident.created_at)
        if recency <= 0.01:
            continue
        distance_km = _min_distance_to_route_km(incident.latitude, incident.longitude, coordinates)
        if distance_km is None or distance_km > HAZARD_RADIUS_KM:
            continue
        matched.append((incident, distance_km, recency))

    if not matched:
        return 0.0, [], []

    total = 0.0
    reasons = []
    # Group by (type, severity) so repeated similar reports reinforce
    # rather than each counting at full independent weight forever.
    seen_types = {}
    for incident, distance_km, recency in sorted(matched, key=lambda m: -m[2]):
        base = SEVERITY_WEIGHT.get(incident.severity, 15)
        proximity_factor = max(0.2, 1.0 - (distance_km / HAZARD_RADIUS_KM))
        contribution = base * recency * proximity_factor
        key = (incident.incident_type, incident.severity)
        # Diminishing returns for repeated similar reports on the same route
        repeat_index = seen_types.get(key, 0)
        contribution *= (0.6 ** repeat_index)
        seen_types[key] = repeat_index + 1
        total += contribution

    total = min(100.0, total)

    # Build a compact, human-readable explanation (most severe/recent first)
    matched.sort(key=lambda m: (-SEVERITY_WEIGHT.get(m[0].severity, 15), m[1]))
    for incident, distance_km, recency in matched[:4]:
        label = incident.incident_type.replace("_", " ")
        reasons.append(
            f"{incident.severity.capitalize()}-severity {label} report ~{round(distance_km, 1)} km from route "
            f"({round(recency * 100)}% recency weight)"
        )

    return round(total, 1), reasons, [m[0] for m in matched]


def calculate_route_risk(route, weather_points, hazard_points=None, incidents=None):
    max_rain = 0.0
    max_probability = 0.0
    for point in weather_points:
        w = point.get("weather", {})
        max_rain = max(max_rain, float(w.get("precipitation_mm", 0) or 0))
        max_probability = max(max_probability, float(w.get("rain_probability", 0) or 0))

    hazard_points = hazard_points or {"flood": [], "landslide": []}
    flood_values = [x["data"]["value"] for x in hazard_points.get("flood", []) if x.get("data", {}).get("value") is not None]
    landslide_values = [x["data"]["value"] for x in hazard_points.get("landslide", []) if x.get("data", {}).get("value") is not None]
    flood_hazard = max(flood_values) if flood_values else None
    landslide_hazard = max(landslide_values) if landslide_values else None

    score = 0
    reasons = []
    if max_rain >= 50:
        score += 35; reasons.append("Heavy rainfall forecast")
    elif max_rain >= 25:
        score += 20; reasons.append("Moderate rainfall forecast")
    elif max_rain >= 10:
        score += 10; reasons.append("Rainfall forecast")
    if max_probability >= 80:
        score += 20; reasons.append("High precipitation probability")
    elif max_probability >= 60:
        score += 10; reasons.append("Elevated precipitation probability")

    if landslide_hazard is not None:
        if landslide_hazard >= 70:
            score += 25; reasons.append("High NASA landslide hazard in the 50 km route area")
        elif landslide_hazard >= 40:
            score += 15; reasons.append("Moderate NASA landslide hazard in the 50 km route area")
    if flood_hazard is not None:
        if flood_hazard >= 70:
            score += 25; reasons.append("High NASA flood hazard in the 50 km route area")
        elif flood_hazard >= 40:
            score += 15; reasons.append("Moderate NASA flood hazard in the 50 km route area")
    if route.get("duration", 0) / 3600 > 12:
        score += 10; reasons.append("Long route duration")

    incident_score = 0.0
    incident_reasons = []
    if incidents:
        incident_score, incident_reasons, _ = score_incidents_near_route(route, incidents)
        # Incidents are weighted most heavily: real, driver-reported,
        # currently-active disruptions should dominate a stale rain forecast.
        score += incident_score
        reasons.extend(incident_reasons)

    score = min(score, 100)
    return {
        "risk": "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW",
        "score": round(score, 1),
        "reasons": reasons or ["No major route-weather-hazard indicators detected"],
        "rainfall_mm": round(max_rain, 2),
        "rain_probability": round(max_probability, 2),
        "flood_hazard": flood_hazard,
        "landslide_hazard": landslide_hazard,
        "incident_score": incident_score,
        "flood_data_source": "NASA GPM/PMM Floods Nowcast" if flood_hazard is not None else "Live data unavailable",
        "landslide_data_source": "NASA GPM/PMM Global Landslide Nowcast" if landslide_hazard is not None else "Live data unavailable"
    }


def get_route_road_names(route):
    names, refs = [], []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            name = (step.get("name") or "").strip()
            ref = (step.get("ref") or "").strip()
            if name and name not in names:
                names.append(name)
            if ref and ref not in refs:
                refs.append(ref)
    return {
        "road_names": names,
        "road_refs": refs,
        "display_name": " / ".join(refs + names) if refs or names else "Road name unavailable"
    }


def build_route_analysis(shipment, db: Session, start_override=None):
    """
    Builds the recommended + alternative route analysis for a shipment.

    start_override: optional {"latitude":..,"longitude":..} to use instead
    of geocoding shipment.origin. Used by the Recheck Route feature so the
    driver's current GPS position becomes the new starting point rather
    than the shipment's original origin.
    """
    origin = start_override or geocode_location(shipment.origin)
    destination = geocode_location(shipment.destination)
    routes = get_routes(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])

    active_incidents = db.query(IncidentDB).filter(IncidentDB.active == True).all()  # noqa: E712

    out = []
    for i, route in enumerate(routes):
        roads = get_route_road_names(route)
        wp = sample_route_weather(route, origin, destination)
        hp = sample_route_hazards(route)
        rr = calculate_route_risk(route, wp, hp, active_incidents)
        out.append({
            "route_number": i + 1,
            "route_name": roads["display_name"],
            "road_names": roads["road_names"],
            "road_refs": roads["road_refs"],
            "distance_km": round(route["distance"] / 1000, 2),
            "duration_minutes": round(route["duration"] / 60, 1),
            "risk": rr,
            "weather_points": wp,
            "hazard_points": hp,
            "geometry": route.get("geometry")
        })
    out.sort(key=lambda x: (x["risk"]["score"], x["duration_minutes"]))
    for rank, item in enumerate(out, 1):
        item["rank"] = rank

    recommended = out[0]
    alternatives_explained = []
    for alt in out[1:]:
        time_delta = round(alt["duration_minutes"] - recommended["duration_minutes"], 1)
        time_note = f"{abs(time_delta):.0f} min slower" if time_delta > 0 else (f"{abs(time_delta):.0f} min faster" if time_delta < 0 else "same duration")
        alternatives_explained.append(
            f"{alt['route_name']}: {time_note} than the recommended route; risk {alt['risk']['risk']} ({alt['risk']['score']}/100)"
        )

    return {
        "shipment_id": shipment.shipment_id,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "origin_coordinates": origin,
        "destination_coordinates": destination,
        "recommended_route": recommended,
        "routes": out,
        "alternatives_summary": alternatives_explained,
        "hazard_radius_km": HAZARD_RADIUS_KM,
        "data_sources": {
            "weather": "Open-Meteo forecast",
            "flood": "NASA GPM/PMM Floods Nowcast",
            "landslide": "NASA GPM/PMM Global Landslide Nowcast",
            "incidents": "Driver-reported incidents (stored, recency-weighted, 50 km corridor)"
        }
    }


# =========================================================
# SHIPMENT-CONDITION RISK
# =========================================================

@app.get("/shipments/{shipment_id}/risk")
def shipment_risk(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    status = (shipment.status or "pending").strip().lower()
    score = {"pending": 10, "in transit": 20, "delayed": 75, "shipment altered": 60, "altered": 60, "delivered": 0}.get(status, 15)
    reason = {
        "pending": "Shipment is still pending",
        "in transit": "Shipment is currently in transit",
        "delayed": "Shipment has been marked Delayed",
        "shipment altered": "Shipment has been marked Shipment Altered",
        "altered": "Shipment has been marked Shipment Altered",
        "delivered": "Shipment has been delivered"
    }.get(status, f"Current shipment status: {shipment.status}")

    return {
        "shipment_id": shipment_id,
        "status": shipment.status,
        "risk": "HIGH" if score >= 70 else "MEDIUM" if score >= 35 else "LOW",
        "score": score,
        "reasons": [reason],
        "note": "Shipment-condition risk only. Route/weather/incident risk is shown in Route Intelligence."
    }


@app.get("/shipments/{shipment_id}/incident-debug")
def incident_debug(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    """
    TEMPORARY diagnostic endpoint. For the shipment's current recommended
    route, shows every active incident in the database with its exact
    distance to the nearest point on that route, so it's possible to see
    in one response whether incidents are (a) stored, (b) marked active,
    (c) within the 50 km corridor, and (d) recent enough to count —
    without needing browser DevTools.
    Remove this endpoint once diagnosis is complete.
    """
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    origin = geocode_location(shipment.origin)
    destination = geocode_location(shipment.destination)
    routes = get_routes(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    route = routes[0]
    geometry = route.get("geometry") or {}
    coordinates = geometry.get("coordinates", []) if isinstance(geometry, dict) else []

    all_incidents = db.query(IncidentDB).all()

    report = []
    for incident in all_incidents:
        recency = _incident_recency_factor(incident.created_at)
        distance_km = _min_distance_to_route_km(incident.latitude, incident.longitude, coordinates) if coordinates else None
        report.append({
            "id": incident.id,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "active": incident.active,
            "latitude": incident.latitude,
            "longitude": incident.longitude,
            "created_at": incident.created_at,
            "age_hours": round((datetime.utcnow() - incident.created_at).total_seconds() / 3600, 2),
            "recency_weight": round(recency, 3),
            "distance_to_route_km": round(distance_km, 2) if distance_km is not None else None,
            "within_50km_corridor": (distance_km is not None and distance_km <= HAZARD_RADIUS_KM),
            "would_count": (
                incident.active
                and recency > 0.01
                and distance_km is not None
                and distance_km <= HAZARD_RADIUS_KM
            )
        })

    return {
        "shipment_id": shipment_id,
        "route_geometry_point_count": len(coordinates),
        "route_first_point": coordinates[0] if coordinates else None,
        "route_last_point": coordinates[-1] if coordinates else None,
        "total_incidents_in_database": len(all_incidents),
        "incidents": report
    }


# =========================================================
# ROUTE INTELLIGENCE ENDPOINT
# =========================================================

@app.get("/shipments/{shipment_id}/route-intelligence")
def route_intelligence(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)
    return build_route_analysis(shipment, db)


# Backward-compatible alias in case any older frontend build still calls
# the previous path shape (/route-intelligence/{id}) mentioned in the
# project history. The canonical, currently-used path is the one above.
@app.get("/route-intelligence/{shipment_id}")
def route_intelligence_alias(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    return route_intelligence(shipment_id, db, authorization)


# =========================================================
# RECHECK ROUTE (uses driver's live GPS as new starting point)
# =========================================================

@app.get("/shipments/{shipment_id}/recheck-route")
def recheck_route(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    """
    Re-runs route intelligence starting from the driver's LATEST GPS
    position instead of the shipment's original origin. This is what
    powers "Recheck Route while travelling": if a new disruption has
    appeared ahead, the system decides between staying on the current
    route or switching, using the remaining journey only — it never
    regenerates a route from the original starting point.
    """
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    latest_location = db.query(GPSLocationDB).filter(
        GPSLocationDB.shipment_db_id == shipment.id
    ).order_by(GPSLocationDB.id.desc()).first()

    if not latest_location:
        raise HTTPException(
            status_code=400,
            detail="No GPS position recorded yet for this shipment. Update GPS before rechecking the route."
        )

    current_position = {"latitude": latest_location.latitude, "longitude": latest_location.longitude, "display_name": "Driver's current position"}
    analysis = build_route_analysis(shipment, db, start_override=current_position)

    recommended = analysis["recommended_route"]
    # "Stay on route" vs "change route" must be driven by the risk score
    # itself, not by whether alternative routes exist. The previous logic
    # only ever recommended a change when len(routes) > 1, so if OSRM
    # returned a single route for this corridor (common on routes with
    # only one drivable road), a HIGH-risk / critical-incident route would
    # silently default to "stay" without the risk ever being checked.
    risk_level = recommended["risk"]["risk"]
    if risk_level == "HIGH":
        decision = "recommend_change" if len(analysis["routes"]) > 1 else "stay_with_caution"
        decision_reason = (
            f"Active disruption near your current position: "
            f"{'; '.join(recommended['risk']['reasons'][:2])}"
        )
        if decision == "stay_with_caution":
            decision_reason += ". No alternative route is available for this corridor — proceed with extreme caution or hold position if possible."
    elif risk_level == "MEDIUM":
        # Only worth switching if a meaningfully safer alternative exists.
        safer_alt = next((r for r in analysis["routes"][1:] if r["risk"]["score"] < recommended["risk"]["score"] - 10), None)
        if safer_alt:
            decision = "recommend_change"
            decision_reason = f"A safer alternative is available: {'; '.join(safer_alt['risk']['reasons'][:2]) or 'lower overall risk score'}."
        else:
            decision = "stay"
            decision_reason = f"Elevated risk noted ({'; '.join(recommended['risk']['reasons'][:2])}), but no meaningfully safer alternative is available."
    else:
        decision = "stay"
        decision_reason = "No active disruption near the remaining route — continue on the current route."

    return {
        "shipment_id": shipment_id,
        "current_position": current_position,
        "decision": decision,
        "decision_reason": decision_reason,
        "recommended_route": recommended,
        "routes": analysis["routes"],
        "alternatives_summary": analysis["alternatives_summary"],
        "data_sources": analysis["data_sources"]
    }


# =========================================================
# ADAPTIVE DISRUPTION-AWARE ROUTE DECISION (explainable, no black-box ML)
# =========================================================

@app.get("/shipments/{shipment_id}/ai-disruption-prediction")
def ai_disruption_prediction(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    """
    Adaptive disruption-aware route decision.

    This intentionally does NOT run an unsupervised anomaly-detection model
    (e.g. IsolationForest) over 2-3 route alternatives for a single trip —
    that is too small a sample to represent real learning and was flagged
    as such. Instead this uses the same weighted, explainable scoring
    layer as Route Intelligence (weather + NASA hazards + real stored
    driver-reported incidents, recency- and proximity-weighted), and
    presents its reasoning explicitly per route, so the decision is
    auditable rather than a black box.
    """
    caller = resolve_caller(authorization, db)
    shipment = resolve_shipment_for_caller(db, shipment_id, caller)

    analysis = build_route_analysis(shipment, db)
    routes = analysis["routes"]

    predictions = []
    for route in routes:
        risk = route["risk"]
        predictions.append({
            "rank": route["rank"],
            "route_name": route["route_name"],
            "disruption_score": risk["score"],
            "risk": risk["risk"],
            "incident_score": risk.get("incident_score", 0.0),
            "reasons": risk["reasons"],
        })

    predictions.sort(key=lambda x: x["disruption_score"], reverse=True)
    most_vulnerable = predictions[0]
    recommended = analysis["recommended_route"]

    why_selected = []
    if len(routes) > 1:
        time_diff = round(routes[1]["duration_minutes"] - recommended["duration_minutes"], 1)
        if time_diff > 0:
            why_selected.append(f"{abs(time_diff):.0f} minutes faster than the next-best alternative")
        elif time_diff < 0:
            why_selected.append(f"Only {abs(time_diff):.0f} minutes slower than a riskier alternative, but meaningfully safer")
    why_selected.extend(recommended["risk"]["reasons"][:3])

    return {
        "shipment_id": shipment_id,
        "recommended_route": {
            "route_name": recommended["route_name"],
            "disruption_score": recommended["risk"]["score"],
            "risk": recommended["risk"]["risk"],
        },
        "why_selected": why_selected,
        "most_vulnerable_route": most_vulnerable,
        "route_predictions": predictions,
        "decision_method": "weighted rule-based scoring (weather + NASA hazard + recency/proximity-weighted incident reports)",
        "features_considered": [
            "route distance", "route duration",
            "Open-Meteo rainfall", "Open-Meteo precipitation probability",
            "NASA flood hazard (50 km corridor)", "NASA landslide hazard (50 km corridor)",
            "driver-reported incident severity, recency, and proximity to route"
        ],
        "note": (
            "This uses transparent weighted scoring rather than an unsupervised model trained on a "
            "handful of route alternatives, since that sample size is too small to represent real "
            "learning. A supervised model becomes appropriate once enough labelled historical "
            "incident/delay outcomes have been collected."
        ),
        "data_sources": analysis["data_sources"]
    }
