# Mock datasets for the datasets command
MOCK_DATASETS = [
    {
        "id": "patient_db",
        "name": "Patient Records",
        "description": "Patient data and medical records"
    }
]

# Mock archetypes for the archetypes command
MOCK_ARCHETYPES = {
    "patient_db": {
        "patient": {
            "patient_id": {"type": "integer", "description": "Patient ID"},
            "age": {"type": "integer", "description": "Patient age"},
            "diagnosis": {"type": "string", "description": "Primary diagnosis"},
            "vitals": {
                "blood_pressure": {"type": "string", "description": "Blood pressure reading"},
                "heart_rate": {"type": "integer", "description": "Heart rate BPM"},
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