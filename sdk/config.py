"""
Configuration for Epsilon SDK
"""

# API Configuration
BASE_URL = "http://localhost:3334"
TIMEOUT = 30

# API Endpoints
ENDPOINTS = {
    "auth": "/api/v1/hub/analysis/auth",
    "datasets": "/api/v1/hub/analysis/datasets",
    "dataset": "/api/v1/hub/analysis/datasets/{dataset_id}"
}

# Credentials Configuration
CREDENTIALS_DIR = ".epsilon_sdk"
CREDENTIALS_FILE = "credentials.ini"