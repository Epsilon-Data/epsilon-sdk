import json
import os


def to_pascal_case(s: str) -> str:
    """Convert a string to PascalCase"""
    return ''.join(word.capitalize() for word in s.replace('-', '_').split('_'))


def generate_class_code(name: str, data: dict, indent: int = 0) -> str:
    """
    Generate Python class code for a JSON structure

    Parameters:
    -----------
    name : str
        Name of the class
    data : dict
        Dictionary representing the structure
    indent : int, optional
        Current indentation level

    Returns:
    --------
    str
        Python class code
    """
    class_name = to_pascal_case(name)
    field_lines = []

    # Class definition
    class_line = f"class {class_name}:"
    class_code = [" " * indent + class_line]

    # Constructor
    init_lines = [" " * (indent + 4) + "def __init__(self, data=None):"]
    init_lines.append(" " * (indent + 8) + "self._data = data or {}")

    # Generate attributes and nested classes
    nested_classes = []

    for key, value in data.items():
        field_name = key

        if isinstance(value, dict):
            # Generate nested class
            nested_class_name = to_pascal_case(key)
            nested_class = generate_class_code(nested_class_name, value, indent + 4)
            nested_classes.append(nested_class)

            # Add property for nested class
            property_lines = [
                " " * (indent + 4) + f"@property",
                " " * (indent + 4) + f"def {key}(self):",
                " " * (indent + 8) + f"data = self._data.get('{key}', {{}})",
                " " * (indent + 8) + f"return {nested_class_name}(data)"
            ]
            field_lines.extend(property_lines)
        else:
            # Add property for simple type
            property_lines = [
                " " * (indent + 4) + f"@property",
                " " * (indent + 4) + f"def {key}(self):",
                " " * (indent + 8) + f"return self._data.get('{key}')"
            ]
            field_lines.extend(property_lines)

    # Add to_dict method
    to_dict_lines = [
        " " * (indent + 4) + "def to_dict(self):",
        " " * (indent + 8) + "return self._data"
    ]

    # Add __repr__ method
    repr_lines = [
        " " * (indent + 4) + "def __repr__(self):",
        " " * (indent + 8) + "return repr(self._data)"
    ]

    # If no attributes, add pass
    if not field_lines and not nested_classes:
        class_code.append(" " * (indent + 4) + "pass")
    else:
        class_code.extend(init_lines)
        class_code.extend(field_lines)
        class_code.extend(to_dict_lines)
        class_code.extend(repr_lines)
        class_code.extend(nested_classes)

    return "\n".join(class_code)


def compile_archetype(json_file_path: str, output_file: str = "generated_models.py"):
    """
    Compile a JSON archetype file into Python classes

    Parameters:
    -----------
    json_file_path : str
        Path to the JSON archetype file
    output_file : str, optional
        Path to save the generated Python models (default: "generated_models.py")

    Returns:
    --------
    str
        Path to the generated Python file
    """
    if not os.path.exists(json_file_path):
        raise FileNotFoundError(f"Archetype file not found: {json_file_path}")

    # Load JSON data
    with open(json_file_path, 'r') as f:
        data = json.load(f)

    # Generate imports
    code = [
        "from typing import Any, Dict, List, Optional",
        "",
        "",
        "def create_dataset(data=None):",
        "    \"\"\"Create a dataset from the given data or load from default\"\"\"",
        "    if data is None:",
        f"        with open('{json_file_path}', 'r') as f:",
        "            import json",
        "            data = json.load(f)",
        "    return Root(data)",
        "",
        ""
    ]

    # Add class definitions
    root_class = generate_class_code("Root", data)
    code.append(root_class)

    # Write code to file
    with open(output_file, 'w') as f:
        f.write("\n".join(code))

    print(f"Generated model classes at {output_file}")
    return output_file