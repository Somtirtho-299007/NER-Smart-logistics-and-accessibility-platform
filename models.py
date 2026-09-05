from sqlalchemy import (
    Column, Integer, String, Float, DateTime, UniqueConstraint, ForeignKey, Boolean
)
from database import Base
from datetime import datetime


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)


class DriverDB(Base):
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(String, unique=True, index=True)
    password = Column(String)


class ShipmentDB(Base):
    """
    IMPORTANT: shipment_id (the human/visible ID, e.g. "SHIP123") is
    intentionally NOT globally unique. Two different owners are allowed to
    use the same visible shipment_id. Uniqueness is only enforced per
    owner, via the composite constraint below.

    All other tables (assignments, GPS, tracking, incidents) reference the
    internal auto-increment primary key `id` (as shipment_db_id) rather
    than the visible shipment_id, so that two different owners' shipments
    that happen to share the same visible ID can never have their
    driver assignments, GPS history, or tracking events mixed up.
    """
    __tablename__ = "shipments"
    __table_args__ = (
        UniqueConstraint("owner_username", "shipment_id", name="uq_owner_shipment"),
    )

    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, index=True)  # NOT globally unique
    origin = Column(String)
    destination = Column(String)
    weight = Column(Float)
    cargo = Column(String)
    status = Column(String, default="pending")
    owner_username = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Populated when a driver accepts a rerouted path from Recheck Route.
    # Lets the dealer's Route Intelligence view show the ACTUAL route the
    # driver is now following, not just the originally planned one.
    active_route_name = Column(String, nullable=True)
    active_route_reason = Column(String, nullable=True)
    active_route_updated_at = Column(DateTime, nullable=True)


class TrackingEventDB(Base):
    __tablename__ = "tracking_events"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), index=True)
    status = Column(String)
    location = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DriverAssignmentDB(Base):
    """
    One row per shipment (by internal DB id, not visible shipment_id).
    A driver may only hold one active assignment at a time (enforced in
    code, matching prior behaviour).
    """
    __tablename__ = "driver_assignments"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), unique=True, index=True)
    driver_username = Column(String, index=True)
    assigned_at = Column(DateTime, default=datetime.utcnow)


class GPSLocationDB(Base):
    __tablename__ = "gps_locations"

    id = Column(Integer, primary_key=True, index=True)
    driver_username = Column(String, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class IncidentDB(Base):
    """
    Driver-reported disruptions. These feed the adaptive route-decision
    layer (see main.py: score_incidents_near_route). Incidents decay in
    influence with age and can be marked inactive (e.g. manually cleared).
    """
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    shipment_db_id = Column(Integer, ForeignKey("shipments.id"), nullable=True, index=True)
    reported_by = Column(String, index=True)  # driver_id
    incident_type = Column(String)  # flood, landslide, road_blockage, accident, other
    severity = Column(String)  # low, medium, high, critical
    latitude = Column(Float)
    longitude = Column(Float)
    road_name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
