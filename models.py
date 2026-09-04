from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from database import Base
from datetime import datetime


class ShipmentDB(Base):
    __tablename__ = "shipments"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, unique=True, index=True)
    origin = Column(String)
    destination = Column(String)
    weight = Column(Float)
    cargo = Column(String)
    status = Column(String, default="pending")
    owner_username = Column(String, index=True)


class TrackingEventDB(Base):
    __tablename__ = "tracking_events"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, index=True)
    status = Column(String)
    location = Column(String)


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String)


class DriverAssignmentDB(Base):
    __tablename__ = "driver_assignments"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, unique=True, index=True)
    driver_username = Column(String, index=True)


class GPSLocationDB(Base):
    __tablename__ = "gps_locations"
    id = Column(Integer, primary_key=True, index=True)
    driver_username = Column(String, index=True)
    shipment_id = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    accuracy = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class DriverDB(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True, index=True)
    driver_id = Column(String, unique=True, index=True)
    password = Column(String)


class RouteIncidentDB(Base):
    __tablename__ = "route_incidents"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, index=True, nullable=True)
    reporter_username = Column(String, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    incident_type = Column(String, index=True)
    severity = Column(String, default="medium")
    road_ref = Column(String, nullable=True, index=True)
    road_name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    photo_url = Column(Text, nullable=True)
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RouteDecisionDB(Base):
    __tablename__ = "route_decisions"
    id = Column(Integer, primary_key=True, index=True)
    shipment_id = Column(String, index=True)
    origin_lat = Column(Float)
    origin_lon = Column(Float)
    current_lat = Column(Float)
    current_lon = Column(Float)
    destination = Column(String)
    selected_signature = Column(String, index=True)
    selected_route_name = Column(String)
    selected_distance_km = Column(Float)
    selected_duration_minutes = Column(Float)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class RoadLearningDB(Base):
    __tablename__ = "road_learning"
    id = Column(Integer, primary_key=True, index=True)
    road_key = Column(String, unique=True, index=True)
    observations = Column(Integer, default=0)
    incident_reports = Column(Integer, default=0)
    blocked_reports = Column(Integer, default=0)
    successful_passes = Column(Integer, default=0)
    delay_minutes_total = Column(Float, default=0.0)
    last_observed_at = Column(DateTime, default=datetime.utcnow)
