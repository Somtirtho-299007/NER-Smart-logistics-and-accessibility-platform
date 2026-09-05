from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint, ForeignKey
from database import Base
from datetime import datetime


class ShipmentDB(Base):
    """
    Shipment database model.
    Uses composite unique constraint (owner_username, shipment_id)
    to allow same shipment_id across different user accounts.
    The internal 'id' field is used for all foreign key relationships.
    """
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)  # Internal DB ID for relationships
    shipment_id = Column(String, index=True)  # User-visible shipment ID (NOT globally unique)
    origin = Column(String)
    destination = Column(String)
    weight = Column(Float)
    cargo = Column(String)
    status = Column(String, default="pending")
    owner_username = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Composite unique constraint: same shipment_id allowed for different owners
    __table_args__ = (
        UniqueConstraint("owner_username", "shipment_id", name="uq_owner_shipment_id"),
    )


class TrackingEventDB(Base):
    """
    Tracking event model.
    References shipment by internal shipment_db_id to prevent cross-account data mixing.
    """
    __tablename__ = "tracking_events"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), index=True)
    shipment_id = Column(String, index=True)  # For display/reference
    status = Column(String)
    location = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserDB(Base):
    """Dealer/User account model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, default="dealer")
    created_at = Column(DateTime, default=datetime.utcnow)


class DriverAssignmentDB(Base):
    """
    Driver assignment model.
    References shipment by internal shipment_db_id.
    Prevents multiple drivers per shipment and vice versa.
    """
    __tablename__ = "driver_assignments"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), index=True)
    shipment_id = Column(String, index=True)  # For display/reference
    driver_username = Column(String, index=True)
    assigned_at = Column(DateTime, default=datetime.utcnow)

    # Each shipment can have only one driver
    __table_args__ = (
        UniqueConstraint("shipment_db_id", name="uq_shipment_driver"),
    )


class GPSLocationDB(Base):
    """
    GPS location tracking model.
    References shipment by internal shipment_db_id to ensure correct driver tracking.
    Stores multiple GPS updates over time for the same shipment.
    """
    __tablename__ = "gps_locations"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), index=True)
    shipment_id = Column(String, index=True)  # For display/reference
    driver_username = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class DriverDB(Base):
    """Driver account model."""
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(String, unique=True, index=True)
    password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class IncidentReportDB(Base):
    """
    Incident/disruption report model.
    Drivers can report incidents (floods, landslides, accidents, road blockages).
    Incidents are considered within a 50km radius of routes for intelligent routing.
    """
    __tablename__ = "incident_reports"

    id = Column(Integer, primary_key=True, index=True)
    driver_username = Column(String, index=True)
    incident_type = Column(String)  # "flood", "landslide", "accident", "road_blockage"
    severity = Column(String)  # "low", "medium", "high", "critical"
    latitude = Column(Float)
    longitude = Column(Float)
    description = Column(String, nullable=True)
    road_name = Column(String, nullable=True)
    reported_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(String, default="active")  # "active", "resolved", "expired"


class RouteAlternativeDB(Base):
    """
    Store calculated route alternatives for caching and analysis.
    Used to provide consistent recommendations and historical analysis.
    """
    __tablename__ = "route_alternatives"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), index=True)
    shipment_id = Column(String, index=True)
    route_number = Column(Integer)
    distance_km = Column(Float)
    duration_minutes = Column(Float)
    risk_score = Column(Float)
    risk_level = Column(String)  # "low", "medium", "high"
    road_names = Column(String, nullable=True)  # JSON string of road names
    calculated_at = Column(DateTime, default=datetime.utcnow)
