"""Noninteractive, staged project initialisation for CLI and browser callers."""
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from sdk.archetype import compile_archetype, generate_csv_dummy_data, verify_synthetic_csv
from sdk.errors import SDKError

MAIN_TEMPLATE = '''from generated.models import create_dataset


def main():
    dataset = create_dataset()
    # Develop your analysis on the local synthetic projection.
    # Return only aggregates approved by the dataset output policy.
    return {"result": "Analysis complete"}


if __name__ == "__main__":
    print(main())
'''

GITIGNORE = """# Epsilon local research files
generated/data.csv
.epsilon/chat/
.epsilon_sdk/
.env
.env.*
credentials.ini
__pycache__/
*.pyc
.ipynb_checkpoints/
"""


def initialise_project(project_dir, dataset_id, client, dummy_data=False, progress=None):
    """Prepare files in isolation and write project.yml only after success.

    Existing researcher files are never overwritten. No process-wide chdir is
    used; a failed request can be retried in the same registered directory.
    """
    progress = progress or (lambda stage, message: None)
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        raise SDKError("The project folder does not exist.")
    if (root / "project.yml").exists():
        raise SDKError("Project already initialized. Choose a new project folder.")
    generated = root / "generated"
    if generated.is_symlink() or (generated.exists() and not generated.is_dir()):
        raise SDKError("The generated path must be a directory inside the project.")
    names = ("__init__.py", "archetype.json", "data.csv", "models.py")
    if any((generated / name).exists() or (generated / name).is_symlink() for name in names):
        raise SDKError("Generated files already exist. Use a new folder to avoid overwriting them.")
    if any((root / name).is_symlink() for name in ("main.py", ".gitignore", "project.yml")):
        raise SDKError("Project setup files must not be symbolic links.")
    progress("access", "Loading the authorised dataset and archetype…")
    archetype = client.get_dataset(dataset_id)
    if not isinstance(archetype, dict) or not isinstance(archetype.get("properties"), dict):
        raise SDKError("The API did not return a valid archetype.")
    archetype_id = str(archetype.get("$id") or dataset_id).split("/")[-1]
    staged = Path(tempfile.mkdtemp(prefix=".epsilon-init-", dir=str(root)))
    installed = []
    warnings = []
    try:
        (staged / "__init__.py").write_text("# Generated files - do not edit manually\n", encoding="utf-8")
        (staged / "archetype.json").write_text(json.dumps(archetype, indent=2), encoding="utf-8")
        descriptor = archetype.get("syntheticData") or {}
        if (archetype.get("syntheticDataUrl") or archetype.get("synthetic_data_url")) and not descriptor.get("available") and not dummy_data:
            warnings.append("This server is older than this SDK and does not provide the supported synthetic download endpoint.")
        synthetic = None
        progress("download", "Preparing the synthetic projection…")
        if dummy_data or not descriptor.get("available"):
            generate_csv_dummy_data(archetype, str(staged / "data.csv"), num_records=10)
            source = "dummy"
            warnings.append("Random dummy data was generated; no synthetic dataset was downloaded.")
        else:
            synthetic = client.download_synthetic_data(dataset_id, str(staged / "data.csv"))
            source = "synthetic"
        progress("validate", "Verifying CSV fields and the schema fingerprint…")
        verify_synthetic_csv(str(staged / "data.csv"), archetype,
                             synthetic.get("schema_hash") if synthetic else None)
        if synthetic and not synthetic.get("schema_hash"):
            warnings.append("The server response is missing the schema-hash header; the pinned hash could not be verified.")
        progress("models", "Generating typed project models…")
        compile_archetype(str(staged / "archetype.json"), str(staged / "models.py"))
        project = {"name": "Epsilon Project - " + archetype_id, "dataset_id": dataset_id,
                   "archetype_id": archetype_id, "entry_point": "main.py", "epsilon": 1.0,
                   "created_at": datetime.now().isoformat(), "data_source": source}
        if synthetic:
            version = synthetic.get("version")
            if version is not None:
                try:
                    version = int(version)
                except (ValueError, TypeError):
                    pass
                project["dataset_version"] = version
            if synthetic.get("schema_hash"):
                project["schema_hash"] = synthetic["schema_hash"]
        progress("project", "Saving the verified project…")
        generated.mkdir(exist_ok=True)
        for name in names:
            target = generated / name
            # Exclusive creation protects existing files even if another CLI
            # initialises the same project while this request downloads.
            with target.open("xb") as stream:
                installed.append(target)
                stream.write((staged / name).read_bytes())
        if not (root / "main.py").exists():
            with (root / "main.py").open("x", encoding="utf-8") as stream:
                installed.append(root / "main.py")
                stream.write(MAIN_TEMPLATE)
        if not (root / ".gitignore").exists():
            with (root / ".gitignore").open("x", encoding="utf-8") as stream:
                installed.append(root / ".gitignore")
                stream.write(GITIGNORE)
        else:
            warnings.append("Your existing .gitignore was preserved. Ensure it excludes generated/data.csv, local transcripts and credentials before committing research files.")
        with (root / "project.yml").open("x", encoding="utf-8") as stream:
            installed.append(root / "project.yml")
            yaml.safe_dump(project, stream, sort_keys=False)
        return {"project": project, "warnings": warnings, "source": source}
    except Exception:
        for path in reversed(installed):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        shutil.rmtree(str(staged))
