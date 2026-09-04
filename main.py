from fastapi import FastAPI, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session
import urllib.parse
import urllib.request
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi import HTTPException
from database import SessionLocal, engine, Base
from models import (
    ShipmentDB,
    TrackingEventDB,
    UserDB,
    DriverAssignmentDB,
    GPSLocationDB,
    DriverDB
)

from fastapi.middleware.cors import CORSMiddleware

from datetime import datetime
import hashlib
import secrets
import json
import urllib.request
import urllib.parse
import math


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------
# FASTAPI
# ---------------------------------------------------------

app = FastAPI(
    title="NER Smart Logistics Intelligence API",
    description="AI-assisted logistics and accessibility platform for the North Eastern Region"
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
# ---------------------------------------------------------

sessions = {}


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
# PASSWORD HELPER
# ---------------------------------------------------------
active_driver_tokens = {}

def hash_password(password: str):
    return hashlib.sha256(
        password.encode()
    ).hexdigest()
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
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )
    if datetime.utcnow() > session["expires_at"]:
        del active_driver_tokens[token]
        raise HTTPException(
            status_code=401,
            detail="Session expired"
        )
    return session["driver_id"]


# ---------------------------------------------------------
# CREATE DEMO USERS
# ---------------------------------------------------------

def create_demo_users():

    db = SessionLocal()

    try:

        dealer = db.query(UserDB).filter(
            UserDB.username == "dealer1"
        ).first()

        if not dealer:

            dealer = UserDB(
                username="dealer1",
                password=hash_password("dealer123"),
                role="dealer"
            )

            db.add(dealer)


        driver = db.query(UserDB).filter(
            UserDB.username == "driver1"
        ).first()

        if not driver:

            driver = UserDB(
                username="driver1",
                password=hash_password("driver123"),
                role="driver"
            )

            db.add(driver)


        db.commit()

    finally:

        db.close()


create_demo_users()


# ---------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------
@app.post("/driver/register")
def driver_register(data: DriverLogin, db: Session = Depends(get_db)):
    existing_driver = db.query(DriverDB).filter(
        DriverDB.driver_id == data.driver_id
    ).first()

    if existing_driver:
        raise HTTPException(
            status_code=400,
            detail="Driver ID already exists"
        )

    new_driver = DriverDB(
        driver_id=data.driver_id,
        password=hash_password(data.password)
    )

    db.add(new_driver)
    db.commit()
    db.refresh(new_driver)

    return {
        "message": "Driver registered successfully",
        "driver_id": new_driver.driver_id
    }
@app.post("/driver/login")
def driver_login(data: DriverLogin, db: Session = Depends(get_db)):
    driver = db.query(DriverDB).filter(
        DriverDB.driver_id == data.driver_id
    ).first()


    if not driver:

        raise HTTPException(
            status_code=401,
            detail="Invalid driver ID or password"
        )


    if driver.password != hash_password(data.password):

        raise HTTPException(
            status_code=401,
            detail="Invalid driver ID or password"
        )


    token = create_driver_token(driver.driver_id)


    return {
        "message": "Login successful",
        "token": token,
        "driver_id": driver.driver_id
    }

@app.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):

    user = db.query(UserDB).filter(
        UserDB.username == data.username
    ).first()


    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )


    if user.password != hash_password(data.password):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )


    token = secrets.token_hex(16)

    sessions[token] = {
        "username": user.username,
        "role": user.role
    }


    return {
        "message": "Login successful",
        "token": token,
        "username": user.username,
        "role": user.role
    }
# ---------------------------------------------------------
# USER / DEALER REGISTRATION
# ---------------------------------------------------------

@app.post("/register")
def register_user(
    data: LoginRequest,
    db: Session = Depends(get_db)
):

    # Check whether username already exists
    existing_user = db.query(UserDB).filter(
        UserDB.username == data.username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    # Create new dealer/user
    new_user = UserDB(
        username=data.username,
        password=hash_password(data.password),
        role="dealer"
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User registered successfully",
        "username": new_user.username,
        "role": new_user.role
    }


# ---------------------------------------------------------
# SESSION CHECK
# ---------------------------------------------------------

def get_current_user(token: str):
    if token not in sessions:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return sessions[token]

def get_current_principal(authorization: str | None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        return {"type": "driver", "username": driver_id, "role": "driver"}
    user = get_current_user(token)
    return {"type": "user", "username": user["username"], "role": user.get("role", "dealer")}

def require_shipment_access(shipment_id: str, authorization: str | None, db: Session):
    principal = get_current_principal(authorization)
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if principal["type"] == "driver":
        assigned = db.query(DriverAssignmentDB).filter(
            DriverAssignmentDB.shipment_id == shipment_id,
            DriverAssignmentDB.driver_username == principal["username"]
        ).first()
        if not assigned:
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    elif shipment.owner_username != principal["username"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return shipment, principal


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@app.get("/")
def home():

    return {
        "message": "NER Smart Logistics API is running!"
    }


# =========================================================
# SHIPMENTS
# =========================================================


@app.post("/shipments/")
def create_shipment(
    shipment: Shipment,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    current_user = get_current_user(token)

    existing = db.query(ShipmentDB).filter(
        ShipmentDB.shipment_id == shipment.shipment_id
    ).first()

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Shipment ID already exists"
        )

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

    return {
        "message": "Shipment created successfully",
        "shipment": new_shipment
    }

# ---------------------------------------------------------
# GET ALL SHIPMENTS
# ---------------------------------------------------------

@app.get("/shipments/")
def get_shipments(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        owner = get_driver_from_token(token)
        ids = {a.shipment_id for a in db.query(DriverAssignmentDB).filter(DriverAssignmentDB.driver_username == owner).all()}
        shipments = db.query(ShipmentDB).filter(ShipmentDB.shipment_id.in_(ids)).all() if ids else []
    else:
        current_user = get_current_user(token)
        shipments = db.query(ShipmentDB).filter(ShipmentDB.owner_username == current_user["username"]).all()
    assignments = {a.shipment_id:a.driver_username for a in db.query(DriverAssignmentDB).all()}
    return {"shipments":[{"shipment_id":x.shipment_id,"origin":x.origin,"destination":x.destination,"weight":x.weight,"cargo":x.cargo,"status":x.status,"owner_username":x.owner_username,"driver_id":assignments.get(x.shipment_id)} for x in shipments]}

# ---------------------------------------------------------
# GET ONE SHIPMENT
# ---------------------------------------------------------

@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    shipment, _ = require_shipment_access(shipment_id, authorization, db)
    return {"shipment": {"shipment_id": shipment.shipment_id, "origin": shipment.origin, "destination": shipment.destination, "weight": shipment.weight, "cargo": shipment.cargo, "status": shipment.status, "owner_username": shipment.owner_username}}

# ---------------------------------------------------------
# UPDATE SHIPMENT
# ---------------------------------------------------------

@app.put("/shipments/{shipment_id}")
def update_shipment(
    shipment_id: str,
    shipment: ShipmentUpdate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        assignment = db.query(DriverAssignmentDB).filter(
            DriverAssignmentDB.shipment_id == shipment_id,
            DriverAssignmentDB.driver_username == driver_id
        ).first()
        if not assignment:
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    else:
        user = get_current_user(token)
        if user.get("role") == "driver":
            raise HTTPException(status_code=403, detail="Driver login required")
        if not db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id, ShipmentDB.owner_username == user["username"]).first():
            raise HTTPException(status_code=403, detail="Access denied")
    existing_shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not existing_shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if shipment.origin is not None: existing_shipment.origin = shipment.origin
    if shipment.destination is not None: existing_shipment.destination = shipment.destination
    if shipment.weight is not None: existing_shipment.weight = shipment.weight
    if shipment.cargo is not None: existing_shipment.cargo = shipment.cargo
    if shipment.status is not None:
        existing_shipment.status = shipment.status
        db.add(TrackingEventDB(shipment_id=shipment_id, status=shipment.status, location=existing_shipment.destination))
    db.commit(); db.refresh(existing_shipment)
    return {"message":"Shipment updated successfully", "shipment":existing_shipment}

# ---------------------------------------------------------
# DELETE
# ---------------------------------------------------------

@app.delete("/shipments/{shipment_id}")
def delete_shipment(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    shipment, principal = require_shipment_access(shipment_id, authorization, db)
    if principal["type"] == "driver":
        raise HTTPException(status_code=403, detail="Drivers cannot delete shipments")
    db.query(TrackingEventDB).filter(TrackingEventDB.shipment_id == shipment_id).delete(synchronize_session=False)
    db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_id == shipment_id).delete(synchronize_session=False)
    db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).delete(synchronize_session=False)
    db.delete(shipment); db.commit()
    return {"message": "Shipment deleted successfully"}

# =========================================================
# TRACKING
# =========================================================


@app.get("/shipments/{shipment_id}/tracking")
def get_tracking_history(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    require_shipment_access(shipment_id, authorization, db)
    events = db.query(TrackingEventDB).filter(TrackingEventDB.shipment_id == shipment_id).all()
    return {"tracking_history": [{"id": e.id, "shipment_id": e.shipment_id, "status": e.status, "location": e.location} for e in events]}

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
    shipment, principal = require_shipment_access(shipment_id, authorization, db)
    if principal["type"] == "driver":
        raise HTTPException(status_code=403, detail="Drivers cannot assign drivers")

    if not shipment:
        raise HTTPException(
            status_code=404,
            detail="Shipment not found"
        )

    driver = db.query(DriverDB).filter(
        DriverDB.driver_id == data.driver_id
    ).first()

    if not driver:
        raise HTTPException(
            status_code=404,
            detail=f"Driver {data.driver_id} not found"
        )

    assignment = db.query(DriverAssignmentDB).filter(
        DriverAssignmentDB.shipment_id == shipment_id
    ).first()

    if assignment:
        raise HTTPException(
            status_code=400,
            detail="Shipment already has a driver assigned"
        )

    occupied = db.query(DriverAssignmentDB).filter(
        DriverAssignmentDB.driver_username == data.driver_id
    ).first()

    if occupied:
        raise HTTPException(
            status_code=400,
            detail="Driver is already assigned to another shipment"
        )

    assignment = DriverAssignmentDB(
        shipment_id=shipment_id,
        driver_username=data.driver_id
    )
    db.add(assignment)

    db.commit()
    db.refresh(assignment)

    return {
        "message": "Driver assigned successfully",
        "shipment_id": shipment_id,
        "driver_id": data.driver_id
    }

# ---------------------------------------------------------
# AVAILABLE DRIVERS
# ---------------------------------------------------------

@app.get("/drivers")
def get_drivers(db: Session = Depends(get_db)):
    occupied = {x.driver_username for x in db.query(DriverAssignmentDB).all()}
    return {"drivers": [
        {"driver_id": d.driver_id}
        for d in db.query(DriverDB).all()
        if d.driver_id not in occupied
    ]}

@app.get("/available-shipments")
def get_available_shipments(db: Session = Depends(get_db)):
    occupied = {x.shipment_id for x in db.query(DriverAssignmentDB).all()}
    return {"shipments": [
        {"shipment_id": x.shipment_id, "origin": x.origin, "destination": x.destination, "status": x.status}
        for x in db.query(ShipmentDB).all()
        if x.shipment_id not in occupied
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
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    driver_id = get_driver_from_token(token)
    assignment = db.query(DriverAssignmentDB).filter(
        DriverAssignmentDB.shipment_id == gps.shipment_id,
        DriverAssignmentDB.driver_username == driver_id
    ).first()
    if not assignment:
        raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    location = GPSLocationDB(driver_username=driver_id, shipment_id=gps.shipment_id, latitude=gps.latitude, longitude=gps.longitude, accuracy=gps.accuracy)
    db.add(location); db.commit(); db.refresh(location)
    return {"message":"GPS updated successfully","driver_id":driver_id,"shipment_id":gps.shipment_id,"latitude":gps.latitude,"longitude":gps.longitude,"accuracy":gps.accuracy,"timestamp":location.timestamp}

# ---------------------------------------------------------
# DRIVER LOCATION
# ---------------------------------------------------------

@app.get("/shipments/{shipment_id}/location")
def get_driver_location(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    current_user = get_current_user(token) if token not in active_driver_tokens else {"role":"driver","username":get_driver_from_token(token)}
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if current_user["role"] == "driver":
        allowed = db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_id == shipment_id, DriverAssignmentDB.driver_username == current_user["username"]).first()
        if not allowed: raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    elif shipment.owner_username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Access denied")
    location = db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).order_by(GPSLocationDB.id.desc()).first()
    if not location: return {"shipment_id":shipment_id,"message":"No GPS data available yet","latitude":None,"longitude":None}
    return {"shipment_id":shipment_id,"driver_id":location.driver_username,"latitude":location.latitude,"longitude":location.longitude,"accuracy":location.accuracy,"timestamp":location.timestamp}

# =========================================================
# GEOCODING
# =========================================================

geocode_cache = {}


def geocode_place(place):

    if place in geocode_cache:

        return geocode_cache[place]


    params = urllib.parse.urlencode({

        "q": place + ", India",

        "format": "jsonv2",

        "limit": 1,

        "countrycodes": "in"
    })


    url = (
        "https://nominatim.openstreetmap.org/search?"
        + params
    )


    request = urllib.request.Request(

        url,

        headers={
            "User-Agent":
            "NER-Smart-Logistics-Prototype/1.0"
        }
    )


    with urllib.request.urlopen(
        request,
        timeout=15
    ) as response:

        data = json.loads(
            response.read().decode()
        )


    if not data:

        raise HTTPException(

            status_code=400,

            detail=f"Could not locate {place}"
        )


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

        "daily":
        "precipitation_sum,"
        "precipitation_probability_max,"
        "weather_code",

        "forecast_days": 1,

        "timezone": "auto"
    })


    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + params
    )


    with urllib.request.urlopen(
        url,
        timeout=15
    ) as response:

        data = json.loads(
            response.read().decode()
        )


    daily = data["daily"]


    return {

        "precipitation_mm":
        daily["precipitation_sum"][0],

        "rain_probability":
        daily["precipitation_probability_max"][0],

        "weather_code":
        daily["weather_code"][0]
    }


# =========================================================
# ROUTE SERVICE
# =========================================================


def get_routes(
    origin_lat,
    origin_lon,
    destination_lat,
    destination_lon
):

    coordinates = (
        f"{origin_lon},{origin_lat};"
        f"{destination_lon},{destination_lat}"
    )

    url = (
        "https://router.project-osrm.org/"
        "route/v1/driving/"
        + coordinates
        + "?alternatives=true"
        + "&overview=full"
        + "&steps=true"
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                "NER-Smart-Logistics-Prototype/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            data = json.loads(
                response.read().decode()
            )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Route service error: {str(e)}"
        )

    if data.get("code") != "Ok":

        raise HTTPException(
            status_code=400,
            detail=f"OSRM error: {data}"
        )

    routes = data.get("routes")

    if not isinstance(routes, list):

        raise HTTPException(
            status_code=500,
            detail="OSRM returned routes in an unexpected format"
        )

    if len(routes) == 0:

        raise HTTPException(
            status_code=404,
            detail="OSRM returned no routes"
        )

    return routes


# =========================================================
# ROUTE WEATHER SAMPLING
# =========================================================


def sample_route_weather(route, origin, destination):

    results = []

    locations = [
        origin,
        destination
    ]

    for location in locations:

        try:

            weather = get_weather(
                location["latitude"],
                location["longitude"]
            )

            results.append({

                "latitude":
                    location["latitude"],

                "longitude":
                    location["longitude"],

                "weather":
                    weather
            })

        except Exception:

            continue

    return results

# =========================================================
# INTELLIGENCE ENGINE
# =========================================================


def calculate_route_risk(

    route,

    weather_points

):

    score = 0

    reasons = []


    max_rain = 0

    max_probability = 0


    for point in weather_points:

        weather = point["weather"]


        max_rain = max(
            max_rain,
            weather["precipitation_mm"]
        )


        max_probability = max(
            max_probability,
            weather["rain_probability"]
        )


    # Heavy rainfall

    if max_rain >= 50:

        score += 35

        reasons.append(
            "Heavy rainfall forecast"
        )

    elif max_rain >= 25:

        score += 20

        reasons.append(
            "Moderate rainfall forecast"
        )

    elif max_rain >= 10:

        score += 10

        reasons.append(
            "Some rainfall forecast"
        )


    # High rain probability

    if max_probability >= 80:

        score += 20

        reasons.append(
            "High probability of precipitation"
        )

    elif max_probability >= 60:

        score += 10

        reasons.append(
            "Elevated precipitation probability"
        )


    # NER terrain heuristic

    ner_points = 0


    for point in weather_points:

        lat = point["latitude"]

        lon = point["longitude"]


        if (

            21.5 <= lat <= 29.5

            and

            88.0 <= lon <= 97.5

        ):

            ner_points += 1


    if ner_points > 0 and max_rain >= 25:

        score += 20

        reasons.append(
            "Rainfall may increase "
            "landslide/accessibility risk "
            "in the NER terrain"
        )


    # Route duration factor

    hours = route["duration"] / 3600


    if hours > 12:

        score += 10

        reasons.append(
            "Long route duration"
        )


    if score >= 50:

        risk = "HIGH"

    elif score >= 25:

        risk = "MEDIUM"

    else:

        risk = "LOW"


    if not reasons:

        reasons.append(
            "No major weather risk indicators detected"
        )


    return {

        "risk": risk,

        "score": min(score, 100),

        "reasons": reasons,

        "rainfall_mm": max_rain,

        "rain_probability": max_probability
    }


# =========================================================
# ROUTE INTELLIGENCE — LIVE WEATHER + NASA EONET HAZARDS
# =========================================================

def geocode_location(location):
    """Geocode an Indian place name, avoiding ambiguous global matches."""
    key = location.strip().lower()
    if key in geocode_cache:
        return geocode_cache[key]

    params = urllib.parse.urlencode({
        "q": location.strip() + ", India",
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "in"
    })
    url = "https://nominatim.openstreetmap.org/search?" + params
    request = urllib.request.Request(url, headers={"User-Agent": "NER-Smart-Logistics-Prototype/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Geocoding service error: {str(e)}")
    if not data:
        raise HTTPException(status_code=404, detail=f"Could not find Indian location: {location}")
    result = {
        "latitude": float(data[0]["lat"]),
        "longitude": float(data[0]["lon"]),
        "display_name": data[0].get("display_name", location)
    }
    geocode_cache[key] = result
    return result


def get_routes(origin_lat, origin_lon, destination_lat, destination_lon):
    coordinates = f"{origin_lon},{origin_lat};{destination_lon},{destination_lat}"
    url = (
        "https://router.project-osrm.org/route/v1/driving/" + coordinates +
        "?alternatives=true&overview=full&geometries=geojson&steps=true"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "NER-Smart-Logistics-Prototype/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Route service error: {str(e)}")
    if data.get("code") != "Ok":
        raise HTTPException(status_code=400, detail=f"OSRM error: {data}")
    routes = data.get("routes", [])
    if not routes:
        raise HTTPException(status_code=404, detail="No route found")
    return routes


def sample_route_points(route, count=5):
    coords = (route.get("geometry") or {}).get("coordinates", []) or []
    if not coords:
        return []
    count = min(count, len(coords))
    indexes = sorted(set(round(i * (len(coords) - 1) / max(count - 1, 1)) for i in range(count)))
    return [{"latitude": float(coords[i][1]), "longitude": float(coords[i][0])}
            for i in indexes if isinstance(coords[i], list) and len(coords[i]) >= 2]


def sample_route_weather(route, origin=None, destination=None):
    results = []
    for point in sample_route_points(route, 5):
        try:
            weather = get_weather(point["latitude"], point["longitude"])
            results.append({**point, "weather": weather})
        except Exception:
            continue
    return results


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))


def _geometry_points(geometry):
    """Extract representative [lon,lat] points from EONET Point/Polygon geometries."""
    if not isinstance(geometry, dict):
        return []
    coords = geometry.get("coordinates")
    out = []
    def walk(x):
        if isinstance(x, (list, tuple)) and len(x) >= 2 and isinstance(x[0], (int,float)) and isinstance(x[1], (int,float)):
            out.append((float(x[1]), float(x[0])))
        elif isinstance(x, (list, tuple)):
            for y in x:
                walk(y)
    walk(coords)
    return out


def get_nasa_eonet_hazards(route):
    """Fetch recent/open NASA EONET Flood and Landslide events near sampled route points.
    These are observed/curated events, NOT invented probabilities.
    """
    points = sample_route_points(route, 5)
    if not points:
        return {"flood": [], "landslide": []}

    found = {"flood": {}, "landslide": {}}
    category_map = {"flood": "floods", "landslide": "landslides"}
    for kind, category in category_map.items():
        for point in points:
            lat, lon = point["latitude"], point["longitude"]
            # ~75 km search box around each route sample; 30-day window keeps it operationally relevant.
            d = 0.75
            bbox = f"{lon-d},{lat+d},{lon+d},{lat-d}"
            params = urllib.parse.urlencode({
                "category": category, "status": "all", "days": 30,
                "limit": 50, "bbox": bbox
            })
            url = "https://eonet.gsfc.nasa.gov/api/v3/events?" + params
            request = urllib.request.Request(url, headers={"User-Agent": "NER-Smart-Logistics-Prototype/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=15) as response:
                    events = json.loads(response.read().decode()).get("events", [])
            except Exception:
                continue
            for event in events:
                event_points = _geometry_points(event.get("geometry"))
                distances = [_haversine_km(lat, lon, ep_lat, ep_lon) for ep_lat, ep_lon in event_points]
                nearest = min(distances) if distances else None
                eid = event.get("id") or event.get("title")
                if eid and (eid not in found[kind] or (nearest is not None and nearest < found[kind][eid]["nearest_km"])):
                    found[kind][eid] = {
                        "id": event.get("id"),
                        "title": event.get("title", "NASA EONET event"),
                        "date": event.get("geometry", [{}])[-1].get("date") if event.get("geometry") else None,
                        "open": event.get("closed") is None,
                        "nearest_km": round(nearest, 1) if nearest is not None else None,
                        "link": event.get("link")
                    }
    return {k: sorted(v.values(), key=lambda x: x["nearest_km"] if x["nearest_km"] is not None else 10**9)[:5] for k,v in found.items()}


def calculate_route_risk(route, weather_points, nasa_hazards):
    max_rain = max((float(p.get("weather", {}).get("precipitation_mm", 0) or 0) for p in weather_points), default=0.0)
    max_probability = max((float(p.get("weather", {}).get("rain_probability", 0) or 0) for p in weather_points), default=0.0)
    floods = nasa_hazards.get("flood", [])
    landslides = nasa_hazards.get("landslide", [])

    score, reasons = 0, []
    if max_rain >= 50: score += 35; reasons.append("Heavy rainfall forecast on sampled route points")
    elif max_rain >= 25: score += 20; reasons.append("Moderate rainfall forecast on sampled route points")
    elif max_rain >= 10: score += 10; reasons.append("Rainfall forecast on sampled route points")
    if max_probability >= 80: score += 20; reasons.append("High precipitation probability")
    elif max_probability >= 60: score += 10; reasons.append("Elevated precipitation probability")

    def hazard_points(events, label):
        nonlocal score
        if not events: return
        nearest = events[0].get("nearest_km")
        if nearest is not None and nearest <= 20: score += 30
        elif nearest is not None and nearest <= 50: score += 20
        else: score += 10
        reasons.append(f"NASA EONET reported {label} event(s) near the sampled route corridor")

    hazard_points(floods, "flood")
    hazard_points(landslides, "landslide")
    if route.get("duration", 0)/3600 > 12:
        score += 10; reasons.append("Long route duration")
    score = min(score, 100)

    def status(events, label):
        if not events:
            return f"No NASA EONET {label} event found within sampled route corridors in the last 30 days"
        e = events[0]
        return f"{len(events)} NASA EONET {label} event(s) found; nearest: {e.get('nearest_km')} km — {e.get('title')}"

    return {
        "risk": "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW",
        "score": score,
        "reasons": reasons or ["No major route-weather or nearby NASA event indicators detected"],
        "rainfall_mm": round(max_rain, 2),
        "rain_probability": round(max_probability, 2),
        "flood_events": floods,
        "landslide_events": landslides,
        "flood_status": status(floods, "flood"),
        "landslide_status": status(landslides, "landslide"),
        "data_sources": ["Open-Meteo forecast", "NASA EONET v3 recent natural-event metadata"],
        "election_probability": None, "riot_probability": None, "bridge_broken_probability": None,
        "election_status": "No live election feed connected",
        "riot_status": "No live incident feed connected",
        "bridge_broken_status": "No live bridge-condition feed connected"
    }


def get_route_road_names(route):
    names, refs = [], []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            name = (step.get("name") or "").strip()
            ref = (step.get("ref") or "").strip()
            if ref and ref not in refs: refs.append(ref)
            if name and name not in names: names.append(name)
    # Keep the UI useful: show major corridor identifiers, not every local turn.
    display_parts = refs[:6] if refs else names[:4]
    return {
        "road_names": names[:12],
        "road_refs": refs[:12],
        "display_name": " → ".join(display_parts) if display_parts else "Road name unavailable"
    }

# =========================================================
# RISK ANALYSIS
# =========================================================
@app.get("/shipments/{shipment_id}/risk")
def shipment_risk(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization: raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        if not db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_id == shipment_id, DriverAssignmentDB.driver_username == driver_id).first():
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    else:
        user = get_current_user(token)
        if user.get("role") not in ("dealer", "user"): raise HTTPException(status_code=403, detail="Not authorized")
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment: raise HTTPException(status_code=404, detail="Shipment not found")
    status = (shipment.status or "pending").strip().lower()
    score = {"pending":10,"in transit":20,"delayed":75,"shipment altered":60,"altered":60,"delivered":0}.get(status,15)
    reason = {"pending":"Shipment is still pending","in transit":"Shipment is currently in transit","delayed":"Shipment has been marked Delayed","shipment altered":"Shipment has been marked Shipment Altered","altered":"Shipment has been marked Shipment Altered","delivered":"Shipment has been delivered"}.get(status, f"Current shipment status: {shipment.status}")
    return {"shipment_id":shipment_id,"status":shipment.status,"risk":"HIGH" if score>=70 else "MEDIUM" if score>=35 else "LOW","score":score,"reasons":[reason],"note":"Shipment-condition risk only. Route/weather and NASA event intelligence is shown in Route Intelligence."}

# =========================================================
# ROUTE INTELLIGENCE ENDPOINT
# =========================================================
@app.get("/shipments/{shipment_id}/route-intelligence")
def route_intelligence(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization: raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        if not db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_id == shipment_id, DriverAssignmentDB.driver_username == driver_id).first():
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    else:
        user = get_current_user(token)
        if user.get("role") not in ("dealer", "user"): raise HTTPException(status_code=403, detail="Not authorized")
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment: raise HTTPException(status_code=404, detail="Shipment not found")

    origin = geocode_location(shipment.origin)
    destination = geocode_location(shipment.destination)
    routes = get_routes(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    out = []
    for i, route in enumerate(routes):
        roads = get_route_road_names(route)
        weather_points = sample_route_weather(route)
        nasa_hazards = get_nasa_eonet_hazards(route)
        risk = calculate_route_risk(route, weather_points, nasa_hazards)
        out.append({
            "route_number": i+1,
            "route_name": roads["display_name"],
            "road_names": roads["road_names"],
            "road_refs": roads["road_refs"],
            "distance_km": round(route["distance"]/1000, 2),
            "duration_minutes": round(route["duration"]/60, 1),
            "risk": risk,
            "weather_points": weather_points,
            "geometry": route.get("geometry")
        })
    out.sort(key=lambda x: (x["risk"]["score"], x["duration_minutes"]))
    for rank, item in enumerate(out, 1): item["rank"] = rank
    return {"shipment_id":shipment_id,"origin":shipment.origin,"destination":shipment.destination,
            "origin_coordinates":origin,"destination_coordinates":destination,
            "recommended_route":out[0],"routes":out}
