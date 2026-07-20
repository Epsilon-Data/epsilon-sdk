import json
import os
import csv
import random
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, List, Union


def download_synthetic_data(url: str, csv_file_path: str, timeout: int = 120) -> str:
    """
    Download a synthetic dataset CSV from a public URL (e.g. a Nectar object store)
    and save it to csv_file_path.

    Used in place of generate_csv_dummy_data when a dataset's archetype provides a
    syntheticDataUrl, so local runs execute against representative synthetic data
    instead of random placeholder values.

    Note: the Epsilon access token is intentionally NOT forwarded. The URL is a
    public object-store link; sending the bearer token to a third-party host would
    leak it.
    """
    # Stream the download so large files are not held fully in memory.
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()

        dest_dir = os.path.dirname(csv_file_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        bytes_written = 0
        with open(csv_file_path, 'wb') as csvfile:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    csvfile.write(chunk)
                    bytes_written += len(chunk)

    if bytes_written == 0:
        raise ValueError(f"Downloaded synthetic dataset is empty: {url}")

    print(f"Downloaded synthetic dataset ({bytes_written:,} bytes) to CSV: {csv_file_path}")
    return csv_file_path


def generate_csv_dummy_data(archetype_data: Dict, csv_file_path: str, num_records: int = 5):
    """
    Generate CSV dummy data based on archetype structure
    This will be called during 'epsilon archetypes' command
    """
    def extract_fields_from_archetype(obj: Dict, prefix: str = "") -> List[tuple]:
        """Extract all fields with their types from JSON Schema structure"""
        fields = []

        # Handle JSON Schema format
        if "properties" in obj:
            # This is a JSON Schema object
            for key, value in obj["properties"].items():
                field_name = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    if "type" in value:
                        if value["type"] == "object" and "properties" in value:
                            # Nested object with properties - recurse
                            nested_fields = extract_fields_from_archetype(value, field_name)
                            fields.extend(nested_fields)
                        else:
                            # Simple field with type
                            fields.append((field_name, value["type"]))
                    else:
                        # Object without explicit type - assume object and recurse
                        nested_fields = extract_fields_from_archetype(value, field_name)
                        fields.extend(nested_fields)
        else:
            # Handle non-schema format (legacy)
            for key, value in obj.items():
                # Skip schema metadata fields
                if key in ["$id", "$schema", "title", "type"]:
                    continue

                field_name = f"{prefix}.{key}" if prefix else key

                if isinstance(value, dict):
                    if "type" in value:
                        # It's a field definition
                        fields.append((field_name, value["type"]))
                    else:
                        # It's a nested object - recurse
                        nested_fields = extract_fields_from_archetype(value, field_name)
                        fields.extend(nested_fields)

        return fields

    def generate_value_by_type(field_type: str, record_index: int, field_name: str) -> str:
        """Generate CSV-friendly string values based on type"""
        # Use field_name and record_index for consistent variation
        seed_value = hash(f"{field_name}_{record_index}") % 1000
        random.seed(seed_value)

        if field_type in ["string", "str", "text"]:
            return f"text_value_{seed_value}"

        elif field_type in ["int", "integer", "number"]:
            return str(random.randint(1, 1000))

        elif field_type in ["float", "double", "decimal"]:
            return str(round(random.uniform(1.0, 1000.0), 2))

        elif field_type in ["bool", "boolean"]:
            return str(random.choice([True, False]))

        elif field_type in ["date", "datetime", "timestamp"]:
            start_date = datetime(2020, 1, 1)
            end_date = datetime(2024, 12, 31)
            random_date = start_date + timedelta(days=random.randint(0, (end_date - start_date).days))
            return random_date.strftime("%Y-%m-%d")

        elif field_type in ["array", "list"]:
            # For CSV, represent arrays as comma-separated values in quotes
            items = [f"item_{i}_{seed_value}" for i in range(2, 4)]
            return f'"{",".join(items)}"'

        else:
            return f"sample_{seed_value}"

    # Extract all fields from archetype
    all_fields = extract_fields_from_archetype(archetype_data)

    if not all_fields:
        print("No fields found in archetype for CSV generation")
        return

    # Create CSV file
    with open(csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
        # Create header row
        fieldnames = [field[0] for field in all_fields]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        # Generate data rows
        for record_index in range(num_records):
            row = {}
            for field_name, field_type in all_fields:
                row[field_name] = generate_value_by_type(field_type, record_index, field_name)
            writer.writerow(row)

    print(f"Generated {num_records} dummy records in CSV: {csv_file_path}")
    return csv_file_path

def generate_all_classes(data: Dict, main_class_name: str = "Root") -> str:
    """Generate all classes with proper ordering to avoid NameError"""

    def collect_nested_classes(obj: Dict, class_name: str, collected_classes: list, indent: int = 0):
        """Recursively collect all nested classes first"""

        if isinstance(obj, dict):
            # Handle JSON Schema format
            if "properties" in obj:
                for key, value in obj["properties"].items():
                    if isinstance(value, dict) and value.get("type") == "object" and "properties" in value:
                        # This is a nested object that needs its own class
                        safe_key = key.replace(" ", "_").replace("-", "_").replace(".", "_")
                        nested_class_name = safe_key.title()

                        # Recursively collect deeper nested classes first
                        collect_nested_classes(value, nested_class_name, collected_classes, indent + 1)

                        # Generate this nested class
                        nested_class_code = generate_single_class(nested_class_name, value, 0)
                        if nested_class_code not in collected_classes:
                            collected_classes.append(nested_class_code)
            else:
                # Legacy format
                for key, value in obj.items():
                    # Skip schema metadata fields
                    if key in ["$id", "$schema", "title", "type"]:
                        continue

                    if isinstance(value, dict) and "type" not in value:
                        # This is a nested object that needs its own class
                        safe_key = key.replace(" ", "_").replace("-", "_").replace(".", "_")
                        nested_class_name = safe_key.title()

                        # Recursively collect deeper nested classes first
                        collect_nested_classes(value, nested_class_name, collected_classes, indent + 1)

                        # Generate this nested class
                        nested_class_code = generate_single_class(nested_class_name, value, 0)
                        if nested_class_code not in collected_classes:
                            collected_classes.append(nested_class_code)

    def generate_single_class(class_name: str, data: Any, indent: int = 0) -> str:
        """Generate a single class"""

        indent_str = "    " * indent
        code = [f"{indent_str}class {class_name}:"]

        if isinstance(data, dict):
            # Generate __init__ method
            code.append(f"{indent_str}    def __init__(self, data):")
            code.append(f"{indent_str}        self._data = data if data else {{}}")
            code.append("")

            # Generate properties for each field
            if "properties" in data:
                # Handle JSON Schema format
                for key, value in data["properties"].items():
                    safe_key = key.replace(" ", "_").replace("-", "_").replace(".", "_")

                    if isinstance(value, dict) and value.get("type") == "object" and "properties" in value:
                        # Nested object - create property that returns another class
                        nested_class_name = safe_key.title()
                        code.append(f"{indent_str}    @property")
                        code.append(f"{indent_str}    def {safe_key}(self):")
                        code.append(f"{indent_str}        # Handle nested field access with dot notation")
                        code.append(
                            f"{indent_str}        if '{key}' in self._data and isinstance(self._data['{key}'], dict):")
                        code.append(f"{indent_str}            return {nested_class_name}(self._data['{key}'])")
                        code.append(f"{indent_str}        # Handle flattened CSV data")
                        code.append(f"{indent_str}        flattened = {{}}")
                        code.append(f"{indent_str}        prefix = '{key}.'")
                        code.append(f"{indent_str}        for k, v in self._data.items():")
                        code.append(f"{indent_str}            if k.startswith(prefix):")
                        code.append(f"{indent_str}                nested_key = k[len(prefix):]")
                        code.append(f"{indent_str}                flattened[nested_key] = v")
                        code.append(f"{indent_str}        return {nested_class_name}(flattened)")
                        code.append("")
                    else:
                        # Simple property (works with both nested JSON and flattened CSV)
                        code.append(f"{indent_str}    @property")
                        code.append(f"{indent_str}    def {safe_key}(self):")
                        code.append(f"{indent_str}        # Try direct access first (JSON format)")
                        code.append(f"{indent_str}        if '{key}' in self._data:")
                        code.append(f"{indent_str}            return self._data['{key}']")
                        code.append(f"{indent_str}        # Try flattened access (CSV format)")
                        code.append(f"{indent_str}        for k, v in self._data.items():")
                        code.append(f"{indent_str}            if k.endswith('.{key}'):")
                        code.append(f"{indent_str}                return v")
                        code.append(f"{indent_str}        return None")
                        code.append("")
            else:
                # Handle legacy format
                for key, value in data.items():
                    # Skip schema metadata fields
                    if key in ["$id", "$schema", "title", "type"]:
                        continue

                    safe_key = key.replace(" ", "_").replace("-", "_").replace(".", "_")

                    if isinstance(value, dict) and "type" not in value:
                        # Nested object - create property that returns another class
                        nested_class_name = safe_key.title()
                        code.append(f"{indent_str}    @property")
                        code.append(f"{indent_str}    def {safe_key}(self):")
                        code.append(f"{indent_str}        # Handle nested field access with dot notation")
                        code.append(
                            f"{indent_str}        if '{key}' in self._data and isinstance(self._data['{key}'], dict):")
                        code.append(f"{indent_str}            return {nested_class_name}(self._data['{key}'])")
                        code.append(f"{indent_str}        # Handle flattened CSV data")
                        code.append(f"{indent_str}        flattened = {{}}")
                        code.append(f"{indent_str}        prefix = '{key}.'")
                        code.append(f"{indent_str}        for k, v in self._data.items():")
                        code.append(f"{indent_str}            if k.startswith(prefix):")
                        code.append(f"{indent_str}                nested_key = k[len(prefix):]")
                        code.append(f"{indent_str}                flattened[nested_key] = v")
                        code.append(f"{indent_str}        return {nested_class_name}(flattened)")
                        code.append("")
                    else:
                        # Simple property (works with both nested JSON and flattened CSV)
                        code.append(f"{indent_str}    @property")
                        code.append(f"{indent_str}    def {safe_key}(self):")
                        code.append(f"{indent_str}        # Try direct access first (JSON format)")
                        code.append(f"{indent_str}        if '{key}' in self._data:")
                        code.append(f"{indent_str}            return self._data['{key}']")
                        code.append(f"{indent_str}        # Try flattened access (CSV format)")
                        code.append(f"{indent_str}        for k, v in self._data.items():")
                        code.append(f"{indent_str}            if k.endswith('.{key}'):")
                        code.append(f"{indent_str}                return v")
                        code.append(f"{indent_str}        return None")
                        code.append("")

        return "\n".join(code)

    # First, collect all nested classes (depth-first)
    nested_classes = []
    collect_nested_classes(data, main_class_name, nested_classes)

    # Then generate the main class
    main_class = generate_single_class(main_class_name, data)

    # Combine all classes with nested classes first
    result = []
    for nested_class in nested_classes:
        result.append(nested_class)
        result.append("")  # Empty line between classes

    result.append(main_class)

    return "\n".join(result)

def compile_archetype(json_file_path: str, output_file: str = "generated_models.py"):
    """
    Enhanced compile function that works with both organized and flat folder structures
    """
    if not os.path.exists(json_file_path):
        raise FileNotFoundError(f"Archetype file not found: {json_file_path}")

    # Load JSON data
    with open(json_file_path, 'r') as f:
        archetype_data = json.load(f)

    # Smart CSV file detection for both organized and flat structures
    archetype_dir = os.path.dirname(json_file_path)
    base_name = os.path.splitext(os.path.basename(json_file_path))[0]

    # Try organized structure first: archetypes/dataset_id/dataset_id_dummy.csv
    csv_file = os.path.join(archetype_dir, f"{base_name}_dummy.csv")

    # Fallback to flat structure: archetypes/dataset_id_dummy.csv
    if not os.path.exists(csv_file):
        parent_dir = os.path.dirname(archetype_dir) if archetype_dir else "."
        csv_file = os.path.join(parent_dir, f"{base_name}_dummy.csv")

    # Last fallback: same directory as JSON
    if not os.path.exists(csv_file):
        csv_file = os.path.join(os.path.dirname(json_file_path), f"{base_name}_dummy.csv")

    # Generate Python class code
    code = [
        "# Auto-generated Python classes from archetype",
        "# Loads dummy data from CSV file for testing",
        "",
        "import csv",
        "import os",
        "from typing import Any, Dict, List, Optional",
        "",
        "",
        "def create_dataset(csv_file=None):",
        "    \"\"\"Create a dataset from CSV dummy data\"\"\"",
        "    if csv_file is None:",
        f"        # Default to dummy CSV file",
        f"        csv_file = 'generated/data.csv'",
        "    ",
        "    if not os.path.exists(csv_file):",
        "        print(f'CSV file not found: {csv_file}')",
        "        print('Run \"epsilon archetypes <dataset_id>\" to generate dummy data')",
        "        return DatasetWrapper([])",
        "    ",
        "    # Load CSV data",
        "    records = []",
        "    with open(csv_file, 'r', encoding='utf-8') as f:",
        "        reader = csv.DictReader(f)",
        "        for row in reader:",
        "            records.append(row)",
        "    ",
        "    print(f'Loaded {len(records)} dummy records from CSV')",
        "    return DatasetWrapper(records)",
        "",
        "",
        "class DatasetWrapper:",
        "    \"\"\"Wrapper for dataset records with easy access\"\"\"",
        "    def __init__(self, records):",
        "        self.records = records if isinstance(records, list) else [records]",
        "    ",
        "    def __len__(self):",
        "        return len(self.records)",
        "    ",
        "    def __iter__(self):",
        "        for record in self.records:",
        "            yield Root(record)",
        "    ",
        "    def __getitem__(self, index):",
        "        return Root(self.records[index])",
        "    ",
        "    @property",
        "    def first(self):",
        "        return Root(self.records[0]) if self.records else None",
        "",
        ""
    ]

    # Add all classes
    all_classes_code = generate_all_classes(archetype_data, "Root")
    code.append(all_classes_code)

    # Write code to file
    with open(output_file, 'w') as f:
        f.write("\n".join(code))

    print(f"Python classes generated: {output_file}")
    print(f"CSV data source: {csv_file}")
    print(f"Example usage:")
    print(f"    from {os.path.splitext(os.path.basename(output_file))[0]} import create_dataset")
    print(f"    dataset = create_dataset()  # Loads CSV dummy data automatically")
    print(f"    print(f'Records: {{len(dataset)}}')")
    print(f"    for record in dataset:")

    # Get the first actual field from properties, not schema metadata
    example_field = "field"
    if archetype_data and "properties" in archetype_data:
        properties = archetype_data["properties"]
        if properties:
            example_field = list(properties.keys())[0]
    elif archetype_data:
        # Legacy format - filter out schema metadata
        data_keys = [k for k in archetype_data.keys() if k not in ["$id", "$schema", "title", "type"]]
        if data_keys:
            example_field = data_keys[0]

    print(f"        print(record.{example_field})")

    return output_file