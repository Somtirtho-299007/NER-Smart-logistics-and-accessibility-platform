NER Smart Logistics

NER Smart Logistics is a web-based logistics management and shipment intelligence platform designed to simplify shipment management, driver coordination, route analysis, and real-time logistics monitoring.

🚚 Features
User / Dealer Features
User registration and login
Create and manage shipments
View all shipments
Assign available drivers to shipments
View assigned driver information
Track shipment status
Check driver GPS location
Shipment risk analysis
Route intelligence and alternative route analysis
Driver Features
Driver registration and login
View assigned shipments
Update shipment status
Update GPS location
Use browser GPS location
Mark shipments as:
Pending
In Transit
Delayed
Delivered
Shipment Altered
Route Intelligence

The platform provides route-based information including:

Recommended route
Alternative routes
Distance and estimated travel duration
Major roads and highways used
Route visualization
Weather-based route conditions
Flood and landslide risk indicators
Risk Analysis

Shipment risk analysis is based on shipment conditions and status, including:

Delayed shipments
Shipment alteration
Other shipment-related risk conditions
🛠️ Technology Stack
Frontend
HTML
CSS
JavaScript
Backend
Python
FastAPI
SQLAlchemy
Additional Services
OpenStreetMap
OSRM for route information
Weather and geolocation services
📁 Project Structure
NER-Smart-Logistics/
│
├── main.py
├── models.py
├── requirements.txt
├── index.html
│
├── database/
│   └── Logistics database
│
└── README.md

The exact project structure may contain additional Python files and configuration files depending on the backend setup.

⚙️ Core Functionality

The application allows users to create shipments and assign available drivers. Drivers can log in separately, view their assigned shipments, update shipment status, and provide GPS coordinates.

Users can then monitor shipment progress, check the driver's latest location, analyze shipment-related risks, and explore route intelligence including recommended and alternative routes.

🔐 Authentication

The platform uses session-based authentication.

After successful login, a session token is generated and used for authenticated requests between the frontend and backend.

The system supports separate authentication flows for:

Users / Dealers
Drivers
🌐 Deployment

The project is designed to be deployed as a web application with:

A hosted FastAPI backend
A hosted frontend
A persistent database

Once deployed, users can access the logistics platform directly through a web browser.

🎯 Project Goal

NER Smart Logistics aims to combine traditional shipment management with intelligent logistics features such as route analysis, driver tracking, shipment risk assessment, and accessibility of real-time logistics information.
