# Kisaan Bharosa

> AI-Powered Input Verification and Marketplace for Pakistani Agriculture  
> Developed for the Alibaba Cloud AI Hackathon 2026

## Overview

Kisaan Bharosa is a full-stack agricultural transparency platform built to combat counterfeit fertilizers, sub-standard pesticides, and uncertified seeds in Pakistan. By combining computer vision with secure backend authentication, the platform enables farmers and agricultural inspectors to verify farm input authenticity instantly and access verified suppliers through a centralized marketplace.

## Architecture and Tech Stack

The application relies on a modular, production-ready full-stack architecture:
* **Backend:** FastAPI (Python 3.11+) utilizing asynchronous routing and Pydantic v2 for data validation.
* **Database and ORM:** SQLite managed via SQLAlchemy ORM, handling persistent user accounts, product catalogs, and audit logs.
* **Authentication:** JSON Web Tokens (JWT) combined with Bcrypt password hashing and role-based access control (farmer, inspector, admin).
* **AI Engine:** Google Gemini Vision (gemini-1.5-flash) for multi-modal counterfeit detection and crop health diagnostics, featuring a fallback heuristic simulation mode for offline development environments.
* **Frontend:** Responsive Single-Page Application (SPA) structured with Tailwind CSS, Jinja2 templating, and vanilla JavaScript.

## Project Structure

```text
Kisaan-Bharosa/
├── database.py         # SQLAlchemy engine and session management
├── models.py           # Database schemas for users, scans, and products
├── schemas.py          # Pydantic validation models
├── auth.py             # JWT token generation and security dependencies
├── gemini_service.py   # Google Gemini AI integration and fallback logic
├── main.py             # FastAPI application entrypoint and routing
├── requirements.txt    # Python package dependencies
├── Dockerfile          # Containerization configuration
├── templates/
│   └── index.html      # Tailwind SPA frontend template
└── static/
    ├── js/
    │   └── app.js      # Frontend state management and API clients
    └── uploads/        # Storage directory for uploaded sample images
