# test_sdk.py
from archetypes.dataset123 import create_dataset

# Create a dataset instance using the default data from the JSON file
dataset = create_dataset()

# Print some values to verify access
print(f"Person's blood type: {dataset.Person.health.bloodType}")
print(f"Person's name: {dataset.Person.name}")

# Test with custom data
custom_data = {
    "Person": {
        "health": {
            "bloodType": "A+",
        },
        "name": "Custom Person"
    }
}

custom_dataset = create_dataset(custom_data)
print(f"Custom person name: {custom_dataset.Person.name}")
print(f"Custom blood type: {custom_dataset.Person.health.bloodType}")

# Test converting back to dictionary
person_dict = dataset.Person.to_dict()
print("Person as dictionary:", person_dict)