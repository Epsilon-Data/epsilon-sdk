# Example usage of Epsilon SDK CLI
from archetypes.dataset123 import create_dataset

# Step 1: Login once
# epsilon login
# This will prompt for username, password, and base URL

# Step 2: List datasets
# epsilon datasets

# Step 3: Download archetype
# epsilon archetypes dataset123

# Step 4: Compile archetype to Python classes
# epsilon compile archetypes/dataset123.json

# After compilation, you can use the generated models:
# from dataset123 import create_dataset
# dataset = create_dataset()
# print(dataset.Person.health.bloodType)

print("Use the epsilon CLI commands to work with the SDK:")
print("1. epsilon login")
print("2. epsilon datasets")
print("3. epsilon archetypes <dataset_id>")
print("4. epsilon compile <archetype_file>")

dataset = create_dataset()

print(dataset.Person.Health.bloodType)