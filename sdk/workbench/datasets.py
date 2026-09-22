"""Approved dataset choices and display metadata, without downloading records."""
from sdk.workbench.errors import NotFound, PublicError


def approved_datasets(client):
    data = client.get_datasets()
    if not isinstance(data, list):
        raise PublicError("The Epsilon API returned an unexpected dataset list.")
    result, seen = [], set()
    for item in data:
        if not isinstance(item, dict):
            continue
        dataset_id = item.get("datasetId") or item.get("projectId") or item.get("id")
        if not isinstance(dataset_id, str) or not 1 <= len(dataset_id) <= 200 or dataset_id in seen:
            continue
        seen.add(dataset_id)
        name = item.get("name") or item.get("packageId")
        result.append({"id": dataset_id, "name": str(name or dataset_id)[:200],
                       "status": "Approved", "description": str(item.get("description") or "")[:500]})
    return result


def require_approved(client, dataset_id):
    selected = next((item for item in approved_datasets(client) if item["id"] == dataset_id), None)
    if selected is None:
        raise NotFound("This dataset is not in your approved dataset list. Refresh the list or check your access.")
    return selected


def dataset_details(client, dataset_id):
    selected = require_approved(client, dataset_id)
    archetype = client.get_dataset(dataset_id)
    if not isinstance(archetype, dict) or not isinstance(archetype.get("properties"), dict):
        raise PublicError("The dataset details are unavailable. Retry or contact your dataset coordinator.")
    descriptor = archetype.get("syntheticData") or {}
    return dict(selected, name=str(archetype.get("title") or selected["name"])[:200],
                description=str(archetype.get("description") or selected["description"])[:500],
                synthetic_available=isinstance(descriptor, dict) and descriptor.get("available") is True)
