# Epsilon SDK - CLI Commands
## Quick Start

```bash
# 0. update changes
pip install -e . 

# 1. Login
epsilon login

# 2. View available datasets
epsilon datasets

# 3. Download dataset archetype
epsilon archetypes healthcare_db

# 4. Generate Python classes from archetype
epsilon compile archetypes/healthcare_db/healthcare_db.json

# 5. Write analysis script & build package
epsilon build example.py

# 6. Middleware server yml analyzer
python server_analyzer.py
```


## For version upgrade

For patch version upgrade (0.1.0 → 0.1.1)
```bash
bump-my-version bump patch
```

For minor version upgrade (0.1.0 → 0.2.0)
```bash
bump-my-version bump minor
```

For major version upgrade (0.1.0 → 1.0.0)
```bash
bump-my-version bump major
```