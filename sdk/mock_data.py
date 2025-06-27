# Mock datasets for the datasets command
MOCK_DATASETS = [
    {
        "id": "customer_db",
        "name": "Customer Database",
        "description": "Customer information with demographics and preferences"
    },
    {
        "id": "healthcare_db",
        "name": "Healthcare Records",
        "description": "Patient data and medical records"
    }
]

# Mock archetypes for the archetypes command
MOCK_ARCHETYPES = {
    "healthcare_db": {
        "patient": {
            "patient_id": {"type": "integer", "description": "Patient ID"},
            "age": {"type": "integer", "description": "Patient age"},
            "diagnosis": {"type": "string", "description": "Primary diagnosis"},
            "admission_date": {"type": "date", "description": "Hospital admission date"},
            "critical": {"type": "boolean", "description": "Critical condition"},
            "medications": {"type": "array", "description": "Current medications"},
            "vitals": {
                "blood_pressure": {"type": "string", "description": "Blood pressure reading"},
                "heart_rate": {"type": "integer", "description": "Heart rate BPM"},
                "stable": {"type": "boolean", "description": "Vitals stable"}
            }
        }
    }
}


def get_mock_datasets():
    """Get list of mock datasets"""
    return MOCK_DATASETS


def get_mock_archetype(dataset_id: str):
    """Get mock archetype for a specific dataset"""
    return MOCK_ARCHETYPES.get(dataset_id)


def get_available_mock_dataset_ids():
    """Get list of available mock dataset IDs"""
    return list(MOCK_ARCHETYPES.keys())