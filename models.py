from sqlalchemy import Column, Integer, String, Float, DateTime
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
