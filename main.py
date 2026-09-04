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
    DriverDB,
    RouteIncidentDB,
    RouteDecisionDB,
    RoadLearningDB
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
# DYNAMIC ROUTE INTELLIGENCE + LEARNING ENGINE
# =========================================================

HAZARD_RADIUS_KM = 50.0
INCIDENT_LOOKBACK_DAYS = 30
INCIDENT_ROUTE_PROXIMITY_KM = 2.0
NASA_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3"
route_cache = {}


def geocode_location(place):
    """Strict India-first geocoder used by routing."""
    return geocode_place(place)


def _request_json(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NER-Smart-Logistics-Prototype/2.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def _bbox_around_point(lat, lon, radius_km=HAZARD_RADIUS_KM):
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / max(111.0 * math.cos(math.radians(lat)), 0.1)
    return lon - lon_delta, lat - lat_delta, lon + lon_delta, lat + lat_delta


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_to_route_distance_km(lat, lon, route_coordinates):
    if not route_coordinates:
        return float("inf")
    best = float("inf")
    for point in route_coordinates[::max(1, len(route_coordinates) // 250)]:
        if len(point) >= 2:
            best = min(best, haversine_km(lat, lon, float(point[1]), float(point[0])))
    return best


def route_coordinates(route):
    geometry = route.get("geometry") or {}
    return geometry.get("coordinates", []) if isinstance(geometry, dict) else []


def sample_route_points(route, count=7):
    coords = route_coordinates(route)
    if not coords:
        return []
    indexes = sorted(set(round(i * (len(coords) - 1) / max(count - 1, 1)) for i in range(count)))
    return [(float(coords[i][1]), float(coords[i][0])) for i in indexes if len(coords[i]) >= 2]


def sample_route_weather(route):
    results = []
    for lat, lon in sample_route_points(route):
        try:
            results.append({"latitude": lat, "longitude": lon, "weather": get_weather(lat, lon)})
        except Exception:
            pass
    return results


def _event_point(event):
    geometry = event.get("geometry") or []
    if not isinstance(geometry, list) or not geometry:
        return None
    latest = geometry[-1]
    coords = latest.get("coordinates") if isinstance(latest, dict) else None
    if isinstance(coords, list) and len(coords) >= 2 and isinstance(coords[0], (int, float)):
        return float(coords[1]), float(coords[0])
    # Polygon / multipoint fallback: use the first coordinate recursively.
    def walk(x):
        if isinstance(x, list) and len(x) >= 2 and all(isinstance(v, (int, float)) for v in x[:2]):
            return float(x[1]), float(x[0])
        if isinstance(x, list):
            for y in x:
                found = walk(y)
                if found:
                    return found
        return None
    return walk(coords)


def get_nasa_events_near_point(lat, lon, category, days=30):
    """NASA EONET continuously updated event metadata, limited to a 50 km bbox."""
    ll_lon, ll_lat, ur_lon, ur_lat = _bbox_around_point(lat, lon, HAZARD_RADIUS_KM)
    # EONET expects minLon,minLat,maxLon,maxLat.
    bbox = f"{ll_lon},{ll_lat},{ur_lon},{ur_lat}"
    params = urllib.parse.urlencode({
        "category": category,
        "status": "open",
        "days": days,
        "limit": 100,
        "bbox": bbox
    })
    try:
        data = _request_json(f"{NASA_EONET_URL}/events?{params}", timeout=20)
    except Exception as exc:
        return {"events": [], "available": False, "status": f"NASA EONET unavailable: {exc}"}

    events = []
    for event in data.get("events", []) if isinstance(data, dict) else []:
        pt = _event_point(event)
        if not pt:
            continue
        distance = haversine_km(lat, lon, pt[0], pt[1])
        if distance <= HAZARD_RADIUS_KM:
            events.append({
                "id": event.get("id"),
                "title": event.get("title"),
                "description": event.get("description"),
                "date": event.get("geometry", [{}])[-1].get("date") if event.get("geometry") else None,
                "latitude": pt[0],
                "longitude": pt[1],
                "distance_km": round(distance, 2),
                "link": event.get("link"),
                "closed": event.get("closed")
            })
    events.sort(key=lambda x: x["distance_km"])
    return {"events": events, "available": True, "status": "NASA live event feed"}


def get_route_nasa_hazards(route):
    """Check flood and landslide events around route points; no invented probabilities."""
    points = sample_route_points(route)
    flood_events, landslide_events = {}, {}
    for lat, lon in points:
        flood = get_nasa_events_near_point(lat, lon, "floods", INCIDENT_LOOKBACK_DAYS)
        landslide = get_nasa_events_near_point(lat, lon, "landslides", INCIDENT_LOOKBACK_DAYS)
        for event in flood["events"]:
            flood_events[event["id"]] = event
        for event in landslide["events"]:
            landslide_events[event["id"]] = event
    return {
        "radius_km": HAZARD_RADIUS_KM,
        "flood": sorted(flood_events.values(), key=lambda x: x["distance_km"]),
        "landslide": sorted(landslide_events.values(), key=lambda x: x["distance_km"]),
        "source": "NASA EONET v3 near-real-time event metadata"
    }


def _road_keys(route):
    keys = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            ref = (step.get("ref") or "").strip()
            name = (step.get("name") or "").strip()
            if ref:
                keys.append(f"ref:{ref}")
            elif name:
                keys.append(f"name:{name.lower()}")
    return list(dict.fromkeys(keys))


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


def get_learning_stats(db, route):
    stats = []
    for key in _road_keys(route):
        row = db.query(RoadLearningDB).filter(RoadLearningDB.road_key == key).first()
        if row:
            stats.append(row)
    observations = sum((x.observations or 0) for x in stats)
    incidents = sum((x.incident_reports or 0) for x in stats)
    blocked = sum((x.blocked_reports or 0) for x in stats)
    delays = sum((x.delay_minutes_total or 0.0) for x in stats)
    passes = sum((x.successful_passes or 0) for x in stats)
    incident_rate = (incidents / observations * 100.0) if observations else 0.0
    blocked_rate = (blocked / observations * 100.0) if observations else 0.0
    avg_delay = (delays / passes) if passes else 0.0
    return {
        "observations": observations,
        "incident_reports": incidents,
        "blocked_reports": blocked,
        "successful_passes": passes,
        "learned_incident_rate": round(incident_rate, 2),
        "learned_blocked_rate": round(blocked_rate, 2),
        "learned_average_delay_minutes": round(avg_delay, 2)
    }


def calculate_dynamic_route_score(route, weather, hazards, db):
    duration = float(route.get("duration", 0)) / 60.0
    risk = 0.0
    reasons = []

    rain = max([float(x.get("weather", {}).get("rain_probability", 0) or 0) for x in weather] or [0])
    rainfall = max([float(x.get("weather", {}).get("precipitation_mm", 0) or 0) for x in weather] or [0])
    flood_count = len(hazards.get("flood", []))
    landslide_count = len(hazards.get("landslide", []))

    if rainfall >= 50:
        risk += 25; reasons.append("heavy rainfall forecast")
    elif rainfall >= 25:
        risk += 12; reasons.append("moderate rainfall forecast")
    if rain >= 80:
        risk += 15; reasons.append("high precipitation probability")
    elif rain >= 60:
        risk += 8; reasons.append("elevated precipitation probability")
    if flood_count:
        risk += min(35, 15 + 5 * min(flood_count, 4)); reasons.append(f"{flood_count} NASA flood event(s) within 50 km")
    if landslide_count:
        risk += min(35, 15 + 5 * min(landslide_count, 4)); reasons.append(f"{landslide_count} NASA landslide event(s) within 50 km")

    learning = get_learning_stats(db, route)
    risk += min(25, learning["learned_incident_rate"] * 0.5)
    risk += min(30, learning["learned_blocked_rate"] * 0.8)
    risk += min(20, learning["learned_average_delay_minutes"] * 0.2)
    if learning["observations"]:
        reasons.append("historical road observations included in AI decision")

    blocked_incidents = []
    coords = route_coordinates(route)
    recent = db.query(RouteIncidentDB).filter(
        RouteIncidentDB.active == True,
        RouteIncidentDB.created_at >= datetime.utcnow() - timedelta(days=INCIDENT_LOOKBACK_DAYS)
    ).all()
    for inc in recent:
        distance = point_to_route_distance_km(inc.latitude, inc.longitude, coords)
        if distance <= INCIDENT_ROUTE_PROXIMITY_KM:
            blocked_incidents.append(inc)
            sev = (inc.severity or "medium").lower()
            risk += {"high": 45, "critical": 60, "medium": 20, "low": 5}.get(sev, 15)
    if blocked_incidents:
        reasons.append(f"{len(blocked_incidents)} recent driver/user incident report(s) on/near route")

    effective_minutes = duration + min(180, risk * 1.5)
    if blocked_incidents:
        effective_minutes += 180

    return {
        "risk_score": round(min(100, risk), 1),
        "risk": "HIGH" if risk >= 55 else "MEDIUM" if risk >= 30 else "LOW",
        "effective_minutes": round(effective_minutes, 1),
        "rain_probability": round(rain, 1),
        "rainfall_mm": round(rainfall, 2),
        "flood_events": hazards.get("flood", []),
        "landslide_events": hazards.get("landslide", []),
        "nearby_incidents": [
            {"id": x.id, "type": x.incident_type, "severity": x.severity, "road_ref": x.road_ref,
             "road_name": x.road_name, "description": x.description, "latitude": x.latitude,
             "longitude": x.longitude, "created_at": x.created_at}
            for x in blocked_incidents
        ],
        "learning": learning,
        "reasons": reasons or ["No current hazard or incident signal detected"]
    }


def build_route_analysis(shipment, db, start_lat=None, start_lon=None, persist_decision=False):
    if start_lat is None or start_lon is None:
        origin = geocode_location(shipment.origin)
        start_lat, start_lon = origin["latitude"], origin["longitude"]
        origin_coordinates = origin
    else:
        origin_coordinates = {"latitude": start_lat, "longitude": start_lon, "display_name": "Driver's last updated location"}
    destination = geocode_location(shipment.destination)
    routes = get_routes(start_lat, start_lon, destination["latitude"], destination["longitude"])
    analysed = []
    for i, route in enumerate(routes):
        roads = get_route_road_names(route)
        weather = sample_route_weather(route)
        hazards = get_route_nasa_hazards(route)
        decision = calculate_dynamic_route_score(route, weather, hazards, db)
        signature = hashlib.sha256(("|".join(_road_keys(route)) + f"|{round(route.get('distance',0)/1000,1)}").encode()).hexdigest()[:16]
        analysed.append({
            "route_number": i + 1,
            "route_name": roads["display_name"],
            "road_names": roads["road_names"],
            "road_refs": roads["road_refs"],
            "road_steps": build_road_steps(route),
            "distance_km": round(route["distance"] / 1000, 2),
            "duration_minutes": round(route["duration"] / 60, 1),
            "risk": decision,
            "route_signature": signature,
            "geometry": route.get("geometry")
        })

    # AI decision: prioritize accessibility/safety, then ETA. A clear 3-min route can beat a blocked 2-min route.
    analysed.sort(key=lambda x: (x["risk"]["effective_minutes"], x["duration_minutes"]))
    for rank, item in enumerate(analysed, 1):
        item["rank"] = rank
        item["recommended"] = rank == 1

    recommended = analysed[0]
    if persist_decision:
        previous = db.query(RouteDecisionDB).filter(RouteDecisionDB.shipment_id == shipment.shipment_id).order_by(RouteDecisionDB.id.desc()).first()
        reason = "; ".join(recommended["risk"]["reasons"][:3])
        db.add(RouteDecisionDB(
            shipment_id=shipment.shipment_id,
            origin_lat=origin_coordinates["latitude"], origin_lon=origin_coordinates["longitude"],
            current_lat=start_lat, current_lon=start_lon, destination=shipment.destination,
            selected_signature=recommended["route_signature"], selected_route_name=recommended["route_name"],
            selected_distance_km=recommended["distance_km"], selected_duration_minutes=recommended["duration_minutes"],
            reason=reason
        ))
        db.commit()
        return _attach_recheck_state(analysed, previous, recommended, shipment.shipment_id, start_lat, start_lon, destination)

    return {
        "shipment_id": shipment.shipment_id,
        "origin": shipment.origin,
        "destination": shipment.destination,
        "origin_coordinates": origin_coordinates,
        "destination_coordinates": destination,
        "current_coordinates": {"latitude": start_lat, "longitude": start_lon},
        "recommended_route": recommended,
        "routes": analysed,
        "hazard_radius_km": HAZARD_RADIUS_KM,
        "ai": {
            "name": "Dynamic Route Decision AI",
            "decision_basis": ["current route ETA", "NASA live natural-event signals", "weather", "driver/user geo-tagged incidents", "learned road history"],
            "note": "The system does not invent flood/landslide probabilities. NASA events are shown as detected events; learned road signals come from stored observations/reports."
        },
        "data_sources": {
            "weather": "Open-Meteo",
            "natural_hazards": "NASA EONET v3 near-real-time event metadata",
            "routing": "OpenStreetMap / OSRM"
        }
    }


def _attach_recheck_state(analysed, previous, recommended, shipment_id, lat, lon, destination):
    return {
        "shipment_id": shipment_id,
        "current_coordinates": {"latitude": lat, "longitude": lon},
        "destination_coordinates": destination,
        "recommended_route": recommended,
        "routes": analysed,
        "hazard_radius_km": HAZARD_RADIUS_KM,
        "route_changed": bool(previous and previous.selected_signature != recommended["route_signature"]),
        "previous_route": {
            "signature": previous.selected_signature,
            "route_name": previous.selected_route_name,
            "distance_km": previous.selected_distance_km,
            "duration_minutes": previous.selected_duration_minutes,
            "created_at": previous.created_at
        } if previous else None
    }


def build_road_steps(route):
    steps = []
    seen = set()
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            name = (step.get("name") or "").strip()
            ref = (step.get("ref") or "").strip()
            label = ref or name
            if not label or label in seen:
                continue
            seen.add(label)
            steps.append({"ref": ref or None, "name": name or None, "road": label})
    return steps


def _authorise_shipment(db, shipment_id, authorization):
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
        return {"role": "driver", "username": driver_id}
    user = get_current_user(token)
    if user.get("role") not in ("dealer", "user"):
        raise HTTPException(status_code=403, detail="Not authorized")
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment or shipment.owner_username != user["username"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return user


@app.get("/shipments/{shipment_id}/risk")
def shipment_risk(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    _authorise_shipment(db, shipment_id, authorization)
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    status = (shipment.status or "pending").strip().lower()
    score = {"pending": 10, "in transit": 20, "delayed": 75, "shipment altered": 60, "altered": 60, "delivered": 0}.get(status, 15)
    return {"shipment_id": shipment_id, "status": shipment.status, "risk": "HIGH" if score >= 70 else "MEDIUM" if score >= 35 else "LOW", "score": score,
            "reasons": [f"Current shipment status: {shipment.status}"], "note": "Shipment-condition risk only. Dynamic route risk is handled by Route Intelligence."}


@app.get("/shipments/{shipment_id}/route-intelligence")
def route_intelligence(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    _authorise_shipment(db, shipment_id, authorization)
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    # Driver routing starts from last GPS; dealer routing starts from shipment origin.
    latest = db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).order_by(GPSLocationDB.id.desc()).first()
    if latest:
        return build_route_analysis(shipment, db, latest.latitude, latest.longitude)
    return build_route_analysis(shipment, db)


@app.get("/shipments/{shipment_id}/recheck-route")
def recheck_route(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    user = _authorise_shipment(db, shipment_id, authorization)
    if user.get("role") != "driver":
        raise HTTPException(status_code=403, detail="Recheck Route is a driver operation")
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    latest = db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).order_by(GPSLocationDB.id.desc()).first()
    if not shipment or not latest:
        raise HTTPException(status_code=400, detail="A latest driver GPS location is required before route recheck")
    return build_route_analysis(shipment, db, latest.latitude, latest.longitude, persist_decision=True)


class RouteIncidentRequest(BaseModel):
    shipment_id: str | None = None
    latitude: float
    longitude: float
    incident_type: str
    severity: str = "medium"
    road_ref: str | None = None
    road_name: str | None = None
    description: str | None = None
    photo_url: str | None = None


@app.post("/route-incidents")
def report_route_incident(data: RouteIncidentRequest, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token in active_driver_tokens:
        reporter = get_driver_from_token(token)
        role = "driver"
    else:
        user = get_current_user(token)
        reporter, role = user["username"], user.get("role")
    if data.shipment_id:
        _authorise_shipment(db, data.shipment_id, authorization)
    incident = RouteIncidentDB(
        shipment_id=data.shipment_id, reporter_username=reporter, latitude=data.latitude, longitude=data.longitude,
        incident_type=data.incident_type.strip(), severity=data.severity.strip().lower(), road_ref=data.road_ref,
        road_name=data.road_name, description=data.description, photo_url=data.photo_url, active=True
    )
    db.add(incident)
    # Online learning update: reports increase the learned incident/blockage history for the named road.
    if data.road_ref or data.road_name:
        key = f"ref:{data.road_ref}" if data.road_ref else f"name:{data.road_name.lower()}"
        row = db.query(RoadLearningDB).filter(RoadLearningDB.road_key == key).first()
        if not row:
            row = RoadLearningDB(road_key=key)
            db.add(row)
        row.observations = (row.observations or 0) + 1
        row.incident_reports = (row.incident_reports or 0) + 1
        if data.severity.lower() in ("high", "critical") or "block" in data.incident_type.lower():
            row.blocked_reports = (row.blocked_reports or 0) + 1
        row.last_observed_at = datetime.utcnow()
    db.commit(); db.refresh(incident)
    return {"message": "Route incident recorded", "incident_id": incident.id, "learning_updated": bool(data.road_ref or data.road_name), "role": role}


@app.get("/route-incidents/nearby")
def nearby_route_incidents(latitude: float, longitude: float, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Login required")
    token = authorization.replace("Bearer ", "").strip()
    if token not in active_driver_tokens:
        get_current_user(token)
    rows = db.query(RouteIncidentDB).filter(
        RouteIncidentDB.active == True,
        RouteIncidentDB.created_at >= datetime.utcnow() - timedelta(days=INCIDENT_LOOKBACK_DAYS)
    ).all()
    result = []
    for x in rows:
        d = haversine_km(latitude, longitude, x.latitude, x.longitude)
        if d <= HAZARD_RADIUS_KM:
            result.append({"id": x.id, "type": x.incident_type, "severity": x.severity, "road_ref": x.road_ref, "road_name": x.road_name, "description": x.description, "distance_km": round(d,2), "created_at": x.created_at})
    result.sort(key=lambda x: x["distance_km"])
    return {"radius_km": HAZARD_RADIUS_KM, "incidents": result}


@app.get("/shipments/{shipment_id}/ai-disruption-prediction")
def ai_disruption_prediction(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    """Compatibility endpoint: the old arbitrary IsolationForest score is gone.

    This endpoint now exposes the actual Dynamic Route Decision AI used by routing.
    """
    _authorise_shipment(db, shipment_id, authorization)
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    latest = db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).order_by(GPSLocationDB.id.desc()).first()
    analysis = build_route_analysis(shipment, db, latest.latitude, latest.longitude) if latest else build_route_analysis(shipment, db)
    return {
        "shipment_id": shipment_id,
        "model": "Dynamic Route Decision AI",
        "model_type": "online/adaptive route scoring",
        "recommended_route": analysis["recommended_route"],
        "route_predictions": analysis["routes"],
        "learning": ["geo-tagged incident reports", "historical road observations", "current route conditions"],
        "note": "This replaces the previous standalone anomaly score. The AI's output is the route decision itself."
    }


@app.get("/shipments/{shipment_id}/route-alert")
def route_alert(shipment_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    user = _authorise_shipment(db, shipment_id, authorization)
    if user.get("role") != "driver":
        raise HTTPException(status_code=403, detail="Driver access required")
    shipment = db.query(ShipmentDB).filter(ShipmentDB.shipment_id == shipment_id).first()
    latest = db.query(GPSLocationDB).filter(GPSLocationDB.shipment_id == shipment_id).order_by(GPSLocationDB.id.desc()).first()
    previous = db.query(RouteDecisionDB).filter(RouteDecisionDB.shipment_id == shipment_id).order_by(RouteDecisionDB.id.desc()).first()
    if not shipment or not latest:
        return {"alert": False, "message": "No GPS position available yet"}
    analysis = build_route_analysis(shipment, db, latest.latitude, latest.longitude)
    rec = analysis["recommended_route"]
    changed = bool(previous and previous.selected_signature != rec["route_signature"])
    incident = bool(rec["risk"].get("nearby_incidents"))
    return {
        "alert": changed or incident,
        "reason": "Route conditions changed ahead" if changed else "New incident detected on/near current route" if incident else "No route change detected",
        "recommended_route": rec,
        "current_coordinates": analysis["current_coordinates"]
    }
