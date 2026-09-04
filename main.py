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

try:
    from sklearn.ensemble import IsolationForest
except ImportError:
    IsolationForest = None


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

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session"
        )

    return sessions[token]


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
def get_shipment(
    shipment_id: str,
    db: Session = Depends(get_db)
):

    shipment = db.query(ShipmentDB).filter(
        ShipmentDB.shipment_id == shipment_id
    ).first()


    if not shipment:

        return {
            "message": "Shipment not found"
        }


    return {
        "shipment": shipment
    }


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
def delete_shipment(
    shipment_id: str,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None)
):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")

    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        raise HTTPException(status_code=403, detail="Drivers cannot delete shipments")

    current_user = get_current_user(token)
    existing_shipment = db.query(ShipmentDB).filter(
        ShipmentDB.shipment_id == shipment_id
    ).first()

    if not existing_shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    if existing_shipment.owner_username != current_user["username"]:
        raise HTTPException(status_code=403, detail="Access denied")

    db.query(TrackingEventDB).filter(TrackingEventDB.shipment_id == shipment_id).delete(synchronize_session=False)
    db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).delete(synchronize_session=False)
    db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_id == shipment_id).delete(synchronize_session=False)
    db.delete(existing_shipment)
    db.commit()

    return {"message": "Shipment deleted successfully"}


# =========================================================
# TRACKING
# =========================================================


@app.get("/shipments/{shipment_id}/tracking")
def get_tracking_history(

    shipment_id: str,

    db: Session = Depends(get_db)

):

    events = db.query(
        TrackingEventDB
    ).filter(
        TrackingEventDB.shipment_id == shipment_id
    ).all()


    return {

        "tracking_history": events
    }




# =========================================================
# DRIVER ASSIGNMENT
# =========================================================


@app.post("/shipments/{shipment_id}/assign-driver")
def assign_driver(
    shipment_id: str,
    data: AssignmentRequest,
    db: Session = Depends(get_db)
):

    shipment = db.query(ShipmentDB).filter(
        ShipmentDB.shipment_id == shipment_id
    ).first()

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


HAZARD_RADIUS_KM = 50.0
NASA_PMM_URL = "https://pmmpublisher.pps.eosdis.nasa.gov/opensearch"

hazard_cache = {}


def _bbox_around_point(lat, lon, radius_km=HAZARD_RADIUS_KM):
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / max(111.0 * math.cos(math.radians(lat)), 1.0)
    return lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta


def _numeric_hazard_value(properties):
    if not isinstance(properties, dict):
        return None
    preferred = [
        "probability", "prob", "hazard", "value", "nowcast",
        "flood_probability", "landslide_probability", "risk"
    ]
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
    # Some hazard products expose probabilities in [0,1]; convert only then.
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
        query = urllib.parse.urlencode({
            "q": dataset,
            "limit": 1,
            "startTime": date,
            "endTime": date
        })
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
        bbox = f"{ll_lon},{ll_lat},{ur_lon},{ur_lat}"
        url = subset_url.replace("{LLlon}", str(ll_lon)) \
                         .replace("{LLlat}", str(ll_lat)) \
                         .replace("{URLon}", str(ur_lon)) \
                         .replace("{URLat}", str(ur_lat))
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
    flood = []
    landslide = []
    for index in indexes:
        point = coordinates[index]
        if not isinstance(point, list) or len(point) < 2:
            continue
        lon, lat = float(point[0]), float(point[1])
        flood.append({"latitude": lat, "longitude": lon, "data": get_nasa_hazard(lat, lon, "flood_nowcast")})
        landslide.append({"latitude": lat, "longitude": lon, "data": get_nasa_hazard(lat, lon, "global_landslide_nowcast_30mn")})
    return {"flood": flood, "landslide": landslide}


def calculate_route_risk(route, weather_points, hazard_points=None):
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

    score = min(score, 100)
    return {
        "risk": "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW",
        "score": score,
        "reasons": reasons or ["No major route-weather-hazard indicators detected"],
        "rainfall_mm": round(max_rain, 2),
        "rain_probability": round(max_probability, 2),
        "flood_hazard": flood_hazard,
        "landslide_hazard": landslide_hazard,
        "flood_data_source": "NASA GPM/PMM Floods Nowcast" if flood_hazard is not None else "Live data unavailable",
        "landslide_data_source": "NASA GPM/PMM Global Landslide Nowcast" if landslide_hazard is not None else "Live data unavailable"
    }


def build_route_analysis(shipment):
    origin = geocode_place(shipment.origin)
    destination = geocode_place(shipment.destination)
    routes = get_routes(origin["latitude"], origin["longitude"], destination["latitude"], destination["longitude"])
    out = []
    for i, route in enumerate(routes):
        roads = get_route_road_names(route)
        wp = sample_route_weather(route, origin, destination)
        hp = sample_route_hazards(route)
        rr = calculate_route_risk(route, wp, hp)
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
    return {
        "shipment_id": shipment.shipment_id,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "origin_coordinates": origin,
        "destination_coordinates": destination,
        "recommended_route": out[0],
        "routes": out,
        "hazard_radius_km": HAZARD_RADIUS_KM,
        "data_sources": {
            "weather": "Open-Meteo forecast",
            "flood": "NASA GPM/PMM Floods Nowcast",
            "landslide": "NASA GPM/PMM Global Landslide Nowcast"
        }
    }


# =========================================================
# ROUTE ROAD NAMES / MAP DATA
# =========================================================

def get_route_road_names(route):
    names = []
    refs = []
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

@app.get("/shipments/{shipment_id}/risk")
def shipment_risk(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization: raise HTTPException(status_code=401, detail="Login required")
    token=authorization.replace("Bearer ","").strip()
    if token in active_driver_tokens:
        driver_id=get_driver_from_token(token)
        if not db.query(DriverAssignmentDB).filter(DriverAssignmentDB.shipment_id==shipment_id,DriverAssignmentDB.driver_username==driver_id).first():
            raise HTTPException(status_code=403,detail="Shipment is not assigned to this driver")
    else:
        user=get_current_user(token)
        if user.get("role") not in ("dealer","user"): raise HTTPException(status_code=403,detail="Not authorized")
    shipment=db.query(ShipmentDB).filter(ShipmentDB.shipment_id==shipment_id).first()
    if not shipment: raise HTTPException(status_code=404,detail="Shipment not found")
    status=(shipment.status or "pending").strip().lower()
    score={"pending":10,"in transit":20,"delayed":75,"shipment altered":60,"altered":60,"delivered":0}.get(status,15)
    reason={"pending":"Shipment is still pending","in transit":"Shipment is currently in transit","delayed":"Shipment has been marked Delayed","shipment altered":"Shipment has been marked Shipment Altered","altered":"Shipment has been marked Shipment Altered","delivered":"Shipment has been delivered"}.get(status,f"Current shipment status: {shipment.status}")
    return {"shipment_id":shipment_id,"status":shipment.status,"risk":"HIGH" if score>=70 else "MEDIUM" if score>=35 else "LOW","score":score,"reasons":[reason],"note":"Shipment-condition risk only. Route/weather risk is shown in Route Intelligence."}


# =========================================================
# ROUTE INTELLIGENCE ENDPOINT
# =========================================================

@app.get("/shipments/{shipment_id}/route-intelligence")
def route_intelligence(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        allowed = db.query(DriverAssignmentDB).filter(
            DriverAssignmentDB.shipment_id == shipment_id,
            DriverAssignmentDB.driver_username == driver_id
        ).first()
        if not allowed:
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    else:
        user = get_current_user(token)
        if user.get("role") not in ("dealer", "user"):
            raise HTTPException(status_code=403, detail="Not authorized")

    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return build_route_analysis(shipment)


# =========================================================
# AI / ML DISRUPTION PREDICTION
# =========================================================

@app.get("/shipments/{shipment_id}/ai-disruption-prediction")
def ai_disruption_prediction(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        driver_id = get_driver_from_token(token)
        allowed = db.query(DriverAssignmentDB).filter(
            DriverAssignmentDB.shipment_id == shipment_id,
            DriverAssignmentDB.driver_username == driver_id
        ).first()
        if not allowed:
            raise HTTPException(status_code=403, detail="Shipment is not assigned to this driver")
    else:
        user = get_current_user(token)
        if user.get("role") not in ("dealer", "user"):
            raise HTTPException(status_code=403, detail="Not authorized")

    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    analysis = build_route_analysis(shipment)
    routes = analysis["routes"]
    if IsolationForest is None:
        raise HTTPException(status_code=500, detail="scikit-learn is not installed")

    feature_rows = []
    for route in routes:
        risk = route["risk"]
        feature_rows.append([
            route["distance_km"],
            route["duration_minutes"],
            risk.get("rainfall_mm", 0) or 0,
            risk.get("rain_probability", 0) or 0,
            risk.get("flood_hazard", 0) or 0,
            risk.get("landslide_hazard", 0) or 0
        ])

    # Unsupervised ML is used because the prototype does not yet have a large,
    # labelled historical disruption dataset. No synthetic labels are created.
    model = IsolationForest(n_estimators=150, random_state=42, contamination="auto")
    model.fit(feature_rows)
    raw_scores = model.decision_function(feature_rows)
    min_score = min(raw_scores)
    max_score = max(raw_scores)
    spread = max(max_score - min_score, 1e-9)

    predictions = []
    for route, raw in zip(routes, raw_scores):
        anomaly = 100.0 * (max_score - raw) / spread if len(routes) > 1 else 50.0
        base = route["risk"]["score"]
        disruption_score = round(min(100.0, max(0.0, 0.65 * base + 0.35 * anomaly)), 1)
        predictions.append({
            "rank": route["rank"],
            "route_name": route["route_name"],
            "ml_disruption_score": disruption_score,
            "ml_anomaly_score": round(anomaly, 1),
            "rule_based_route_score": base,
            "risk": "HIGH" if disruption_score >= 70 else "MEDIUM" if disruption_score >= 35 else "LOW"
        })

    predictions.sort(key=lambda x: x["ml_disruption_score"], reverse=True)
    top = predictions[0]
    return {
        "shipment_id": shipment_id,
        "prediction": top,
        "route_predictions": predictions,
        "model": "IsolationForest",
        "model_type": "unsupervised anomaly detection",
        "features": ["route distance", "route duration", "Open-Meteo rainfall", "Open-Meteo precipitation probability", "NASA flood hazard", "NASA landslide hazard"],
        "training_note": "The model uses current route alternatives as observations and does not create synthetic disruption labels. A supervised model will be appropriate once sufficient labelled historical incident/delay data is collected.",
        "data_sources": analysis["data_sources"]
    }
