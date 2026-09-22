"""
The shape of the model's research-question suggestions.

A model proposes specific questions grounded in the measured fields; the
workbench (sdk/workbench/assistant.py) then rebuilds every proposal through
the analysis catalogue, so a suggestion naming fields that do not exist, or an
analysis the matcher blocks, never reaches the researcher.
"""
from sdk import catalogue as catalogue_mod

SCHEMA = {
    "type": "object",
    "required": ["suggestions"],
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "question", "analysis", "fields"],
                "properties": {
                    "title": {"type": "string"},
                    "question": {"type": "string"},
                    "why": {"type": "string"},
                    "analysis": {
                        "type": "string",
                        "enum": sorted(catalogue_mod.SPECS_BY_KEY),
                    },
                    "fields": {
                        "type": "object",
                        "description": "Parameter name to field path, e.g. "
                                       "{\"rows\": \"patient.gender\"}",
                    },
                },
            },
        }
    },
}
