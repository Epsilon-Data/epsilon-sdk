# Epsilon SDK - CLI Commands

## Quick Start

```bash
# 0. Install SDK
pip install epsilon-sdk

# 1. Login to Epsilon
epsilon login

# 2. View available datasets
epsilon datasets

# 3. Initialize project with a dataset
epsilon init <dataset_id>

# 4. Write your analysis in main.py
# (Edit the generated main.py file)

# 5. Test locally with dummy data
epsilon run

# 6. Build for server deployment
epsilon build
```

## Project Workflow

The Epsilon SDK uses a **project-based workflow**:

### 1. Project Structure
After `epsilon init`, you get a clean project structure:
```
your-project/
├── main.py              #  Your analysis script
├── project.yml          #  Project configuration
├── generated/           #  SDK files (auto-generated)
│   ├── archetype.json   #  Dataset schema
│   ├── models.py        #  Python data models
│   └── data.csv         #  Dummy data (for local testing)
└── .gitignore          # Git configuration
```

### 2. Development Flow
1. **`epsilon init <dataset_id>`** - Sets up complete project
2. **Edit `main.py`** - Write your data analysis
3. **`epsilon run`** - Test locally with dummy data
4. **`epsilon build`** - Package for server deployment

### 3. Example Analysis
```python
# main.py
from generated.models import create_dataset

def main():
    # Load the dataset
    dataset = create_dataset()
    print(f"Analyzing {len(dataset)} records")

    # Your analysis code
    for record in dataset:
        print(f"Patient {record.patient.id}: age {record.patient.age}")
        print(f"Heart rate: {record.vitals.heartrate}")

    return {"average_age": 45.2, "total_patients": len(dataset)}

if __name__ == "__main__":
    result = main()
    print(result)
```

## Additional Commands

- **`epsilon status`** - Check login status and server
- **`epsilon clean`** - Remove project files to start over
- **`epsilon change-server <url>`** - Switch to different server
- **`epsilon version`** - Show SDK version

## Installation

```bash
pip install epsilon-sdk
```

PyPI: https://pypi.org/project/epsilon-sdk/

## Release (for maintainers)

```bash
git checkout main
git pull origin main
bump-my-version bump patch   # or minor/major
git push origin main --tags
```

This triggers GitHub Actions → publishes to PyPI automatically.