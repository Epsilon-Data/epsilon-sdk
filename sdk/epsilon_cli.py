import subprocess
import sys
import warnings

# Suppress urllib3 warnings about OpenSSL
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL')

import typer
import json
import os
import configparser
from pathlib import Path
from datetime import datetime
import yaml
from .client import APIClient
from .errors import AuthenticationError, SDKError
from sdk.archetype import compile_archetype as compile_arch
from sdk.archetype import generate_csv_dummy_data
from sdk.archetype import verify_synthetic_csv
from . import config as sdk_config
import re
import shutil
import traceback

app = typer.Typer(
    help="CLI for epsilon SDK: working with datasets, authentication, and generating Python model classes.")

# Configuration directory and file paths
CONFIG_DIR = Path.home() / ".epsilon_sdk"
CONFIG_PATH = CONFIG_DIR / "credentials.ini"


def get_client() -> APIClient:
    """Get API client with stored credentials."""
    return APIClient.from_config(CONFIG_PATH)


@app.command()
def login(
        username: str = typer.Option(..., prompt=True, help="Your username or email."),
        password: str = typer.Option(..., prompt=True, hide_input=True, help="Your password."),
):
    """
    Authenticate with Keycloak and store access token locally.
    """
    try:
        # Construct the auth URL from base URL
        typer.echo("Authenticating with Epsilon...")
        client = APIClient()  # Create new client for login
        client.authenticate(username, password)
        # Store the credentials and configuration
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config = configparser.ConfigParser()
        if CONFIG_PATH.exists():
            config.read(CONFIG_PATH)
        config["default"] = {
            "access_token": client.access_token,
            "expires_at": client.token_expires_at.isoformat() if client.token_expires_at else "",
            "username": username
        }
        with open(CONFIG_PATH, "w") as f:
            config.write(f)
        # Show token expiration time
        if client.token_expires_at:
            typer.echo(f"Token expires at: {client.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        typer.echo("Success")
    except AuthenticationError as e:
        typer.secho(f"Authentication failed: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def status():
    """
    Check your authentication status and current server.
    """

    typer.secho("Epsilon SDK Status", fg=typer.colors.BLUE, bold=True)
    typer.echo(f"Server: {sdk_config.BASE_URL}")
    typer.echo()

    if not CONFIG_PATH.exists():
        typer.secho("Status: Not logged in", fg=typer.colors.RED)
        typer.echo("Run 'epsilon login' to get started")
        return

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)

    if "default" not in config:
        typer.secho("Status: No credentials found", fg=typer.colors.RED)
        typer.echo("Run 'epsilon login' to authenticate")
        return

    creds = config["default"]
    username = creds.get("username", "Unknown")
    typer.secho(f"Logged in as: {username}", fg=typer.colors.GREEN)


@app.command(name="change-server")
def change_server(
        url: str = typer.Argument(..., help="New server URL")
):
    """
    Change which server you're connecting to.
    """
    # Validate URL
    if not url.startswith(('http://', 'https://')):
        typer.secho("Error: Please provide a valid URL starting with http:// or https://", fg=typer.colors.RED)
        raise typer.Exit(1)

    # Clean up URL
    url = url.rstrip('/')

    try:
        # Update config file
        config_file = Path(__file__).parent / "config.py"

        with open(config_file, 'r') as f:
            content = f.read()
        # Update BASE_URL
        updated = re.sub(
            r'BASE_URL = "[^"]*"',
            f'BASE_URL = "{url}"',
            content
        )
        with open(config_file, 'w') as f:
            f.write(updated)
        typer.secho(f"Server updated to: {url}", fg=typer.colors.GREEN)
        typer.echo("Note: You'll need to login again with 'epsilon login'")

    except Exception as e:
        typer.secho(f"Failed to update server: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def datasets():
    """
    List available datasets from the Epsilon API.
    """
    try:
        # API call
        client = get_client()
        datasets = client.get_datasets()

        if not datasets:
            typer.secho("No datasets available", fg=typer.colors.YELLOW)
            typer.echo("You may need to create or request access to datasets")
            return

        typer.secho("Available datasets:", fg=typer.colors.BLUE)
        for idx, dataset in enumerate(datasets, 1):
            # Handle different field names from API
            dataset_id = dataset.get('datasetId', dataset.get('projectId', dataset.get('id', 'N/A')))
            package_id = dataset.get('packageId', '')
            name = dataset.get('name', package_id if package_id else 'Unnamed')
            last_modified = dataset.get('lastModified', '')
            status = dataset.get('status', '')

            typer.echo(f"{idx}. Dataset ID: {dataset_id}")
            if package_id:
                typer.echo(f"   Package: {package_id}")
            if last_modified:
                typer.echo(f"   Last Modified: {last_modified}")
            if status:
                typer.echo(f"   Status: {status}")
            if "university" in dataset:
                typer.echo(f"   University: {dataset['university']}")
            if "faculty" in dataset:
                typer.echo(f"   Faculty: {dataset['faculty']}")
            typer.echo("")

    except AuthenticationError as e:
        typer.secho(f"Authentication error: {e}", fg=typer.colors.RED)
        typer.echo("Please run 'epsilon login' to authenticate")
        raise typer.Exit(1)
    except SDKError as e:
        typer.secho(f"API error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def init(
        dataset_id: str = typer.Argument(..., help="ID of the dataset to initialize project with."),
        dummy_data: bool = typer.Option(False, "--dummy-data",
                                        help="Generate random dummy data locally instead of downloading the synthetic dataset.")
):
    """
    Initialize a new Epsilon project with a dataset.
    Creates project.yml, downloads archetype, generates models and dummy data.
    """
    try:
        # Check if project already exists
        if os.path.exists("project.yml"):
            typer.secho("Project already initialized. Use 'epsilon clean' to start over.", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        typer.secho(f"Initializing project with dataset: {dataset_id}", fg=typer.colors.BLUE)

        client = get_client()

        # Create generated directory for SDK files
        os.makedirs("generated", exist_ok=True)

        # Create __init__.py to make generated a Python package
        with open("generated/__init__.py", 'w') as f:
            f.write('# Generated files - do not edit manually\n')
        typer.secho("✓ Created generated/__init__.py", fg=typer.colors.GREEN)

        # Download archetype
        typer.echo("Downloading archetype...")
        archetype_data = client.get_dataset(dataset_id)

        # Get archetype_id from the $id field in the archetype JSON
        # Format is "project_id/archetype_id", we need just the archetype_id
        full_id = archetype_data.get('$id', dataset_id)
        archetype_id = full_id.split('/')[-1]
        typer.echo(f"Archetype ID: {archetype_id}")

        # Save archetype in generated folder
        with open("generated/archetype.json", 'w') as f:
            json.dump(archetype_data, f, indent=2)
        typer.secho("✓ Created generated/archetype.json", fg=typer.colors.GREEN)

        # Populate generated/data.csv for local testing.
        # Prefer the archetype-scoped synthetic dataset projection served by
        # the hub; dummy data only on explicit request or when no synthetic
        # dataset is attached.
        synthetic_info = None
        descriptor = archetype_data.get("syntheticData") or {}
        if dummy_data:
            typer.echo("Generating random dummy data (--dummy-data)...")
            generate_csv_dummy_data(archetype_data, "generated/data.csv", num_records=10)
            typer.secho("✓ Created generated/data.csv (random dummy data)", fg=typer.colors.GREEN)
        elif descriptor.get("available"):
            typer.echo("Downloading synthetic dataset...")
            try:
                synthetic_info = client.download_synthetic_data(dataset_id, "generated/data.csv")
                verify_synthetic_csv("generated/data.csv", archetype_data, synthetic_info.get("schema_hash"))
            except (SDKError, ValueError) as e:
                # Remove the rejected download so a failed init leaves no
                # stale data.csv behind.
                if os.path.exists("generated/data.csv"):
                    os.remove("generated/data.csv")
                typer.secho(f"Synthetic dataset download failed: {e}", fg=typer.colors.RED)
                typer.echo(f"Use 'epsilon init {dataset_id} --dummy-data' to proceed with random data instead.")
                raise typer.Exit(1)
            schema_hash = synthetic_info.get("schema_hash")
            version = synthetic_info.get("version")
            if not schema_hash:
                typer.secho(
                    "Warning: the server response is missing the schema-hash header; "
                    "the download could not be verified against the archetype's pinned hash.",
                    fg=typer.colors.YELLOW,
                )
            detail = "synthetic dataset"
            if schema_hash:
                detail += f", schema {schema_hash[:12]}"
            if version is not None:
                detail += f", version {version}"
            typer.secho(f"✓ Created generated/data.csv ({detail})", fg=typer.colors.GREEN)
        else:
            if archetype_data.get("syntheticDataUrl") or archetype_data.get("synthetic_data_url"):
                typer.secho(
                    "Warning: the server returned 'syntheticDataUrl', which this SDK no longer supports "
                    "— the server is older than this SDK.",
                    fg=typer.colors.YELLOW,
                )
            typer.echo("No synthetic dataset attached to this dataset — generating dummy data.")
            generate_csv_dummy_data(archetype_data, "generated/data.csv", num_records=10)
            typer.secho("✓ Created generated/data.csv (dummy data)", fg=typer.colors.GREEN)

        # Compile to models.py in generated folder
        typer.echo("Generating Python models...")
        compile_arch("generated/archetype.json", "generated/models.py")
        typer.secho("✓ Created generated/models.py", fg=typer.colors.GREEN)

        # Create project.yml
        project_config = {
            'name': f'Epsilon Project - {archetype_id}',
            'dataset_id': dataset_id,
            'archetype_id': archetype_id,
            'entry_point': 'main.py',
            'epsilon': 1.0,
            'created_at': datetime.now().isoformat()
        }

        # Pin the synthetic dataset version and schema hash the project was
        # initialized against (only when synthetic data was downloaded and
        # the server actually reported the values — never pin nulls).
        if synthetic_info is not None:
            raw_version = synthetic_info.get("version")
            if raw_version is not None:
                try:
                    project_config['dataset_version'] = int(raw_version)
                except (TypeError, ValueError):
                    project_config['dataset_version'] = raw_version
            if synthetic_info.get("schema_hash"):
                project_config['schema_hash'] = synthetic_info.get("schema_hash")

        with open("project.yml", 'w') as f:
            yaml.dump(project_config, f, default_flow_style=False, indent=2)
        typer.secho("✓ Created project.yml", fg=typer.colors.GREEN)

        # Create template main.py
        main_template = '''from generated.models import create_dataset

def main():
    # Load the dataset
    dataset = create_dataset()
    print(f"Loaded {len(dataset)} records")

    # Your analysis code here
    for record in dataset:
        # Example: Access fields from your archetype
        # print(record.field_name)
        pass

    return {"result": "Analysis complete"}

if __name__ == "__main__":
    result = main()
    print(result)
'''
        with open("main.py", 'w') as f:
            f.write(main_template)
        typer.secho("✓ Created main.py template", fg=typer.colors.GREEN)

        # Create .gitignore
        gitignore_content = '''# Epsilon project files
generated/data.csv      # Never commit dummy data - replaced with real data on server
*.pyc
__pycache__/
.epsilon_sdk/
'''
        with open(".gitignore", 'w') as f:
            f.write(gitignore_content)
        typer.secho("✓ Created .gitignore", fg=typer.colors.GREEN)

        typer.echo()
        typer.secho("Project initialized successfully!", fg=typer.colors.GREEN, bold=True)
        typer.echo("Next steps:")
        typer.echo("  1. Edit main.py to write your analysis")
        typer.echo("  2. Run 'epsilon run' to test locally")

    except typer.Exit:
        # Let intentional exits propagate untouched instead of being
        # re-reported as 'Error: 1' by the generic handler below.
        raise
    except AuthenticationError as e:
        typer.secho(f"Authentication error: {e}", fg=typer.colors.RED)
        typer.echo("Please run 'epsilon login' to authenticate")
        raise typer.Exit(1)
    except SDKError as e:
        typer.secho(f"API error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def run():
    """
    Run the project locally with dummy data.
    """
    try:
        # Check if we're in a project directory
        if not os.path.exists("project.yml"):
            typer.secho("Error: Not in an Epsilon project directory.", fg=typer.colors.RED)
            typer.echo("Run 'epsilon init <dataset_id>' to create a project.")
            raise typer.Exit(1)

        # Load project config
        with open("project.yml", 'r') as f:
            project = yaml.safe_load(f)

        entry_point = project.get('entry_point')

        if not os.path.exists(entry_point):
            typer.secho(f"Error: Entry point '{entry_point}' not found.", fg=typer.colors.RED)
            raise typer.Exit(1)

        typer.echo(f"Running {entry_point} locally...")

        # Run the Python script
        result = subprocess.run([sys.executable, entry_point],
                                capture_output=True, text=True)

        if result.stdout:
            typer.echo(result.stdout)

        if result.stderr:
            typer.secho(result.stderr, fg=typer.colors.RED)

        if result.returncode != 0:
            typer.secho(f"Script exited with code {result.returncode}", fg=typer.colors.RED)
            raise typer.Exit(result.returncode)

        typer.secho("✓ Script completed successfully", fg=typer.colors.GREEN)

    except typer.Exit:
        raise
    except Exception as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def clean():
    """
    Clean project files (generated/ folder, main.py, project.yml).
    """

    files_to_clean = ["project.yml", "main.py", ".gitignore"]
    dirs_to_clean = ["generated", "build"]

    cleaned = []

    # Clean files
    for file in files_to_clean:
        if os.path.exists(file):
            os.remove(file)
            cleaned.append(file)

    # Clean directories
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            cleaned.append(f"{dir_name}/")

    if cleaned:
        typer.secho(f"Cleaned: {', '.join(cleaned)}", fg=typer.colors.GREEN)
    else:
        typer.echo("No project files to clean")


@app.command()
def build(
        output_dir: str = typer.Option("./build", help="Output directory")
):
    """
    Build analysis package from project configuration.
    Reads project.yml to get entry point and dataset information.
    """
    try:
        # Check if we're in a project directory
        if not os.path.exists("project.yml"):
            typer.secho("Error: Not in an Epsilon project directory.", fg=typer.colors.RED)
            typer.echo("Run 'epsilon init <dataset_id>' to create a project first.")
            raise typer.Exit(1)

        # Load project config
        with open("project.yml", 'r') as f:
            project = yaml.safe_load(f)

        analysis_script = project.get('entry_point', 'main.py')
        dataset_id = project.get('dataset_id')
        archetype_id = project.get('archetype_id')

        os.makedirs(output_dir, exist_ok=True)

        print(f"Building analysis package from: {analysis_script}")
        print(f"Dataset: {dataset_id} (archetype: {archetype_id})")

        if not os.path.exists(analysis_script):
            typer.secho(f"Script not found: {analysis_script}", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Create dataset info from project configuration
        datasets = [{
            'dataset_id': dataset_id,
            'archetype_id': archetype_id,
            'import_path': 'generated.models',
            'function_name': 'create_dataset',
            'archetype_path': 'generated/archetype.json'
        }]

        print(f"Using dataset: {dataset_id} (archetype: {archetype_id})")

        # Copy generated folder to build directory
        print("Copying generated files...")
        if os.path.exists("generated"):
            shutil.copytree("generated", os.path.join(output_dir, "generated"), dirs_exist_ok=True)
            print("Copied generated/ folder")

        # Generate requirements.txt using pip freeze
        print("Generating requirements.txt...")

        try:
            # Run pip freeze to get current environment packages
            result = subprocess.run([sys.executable, '-m', 'pip', 'freeze'],
                                    capture_output=True, text=True, check=True)

            pip_freeze_output = result.stdout.strip()

            if pip_freeze_output:
                requirements_content = [
                    "# Auto-generated requirements using pip freeze",
                    f"# Generated from: {analysis_script}",
                    f"# Generated at: {datetime.now()}",
                    "",
                    pip_freeze_output
                ]

                print(f"Captured {len([l for l in pip_freeze_output.split() if l.strip()])} packages")
            else:
                requirements_content = [
                    "# No packages found in current environment",
                    f"# Generated at: {datetime.now()}"
                ]
                print("No packages found in current environment")

        except subprocess.CalledProcessError as e:
            print(f"Could not run pip freeze: {e}")
            requirements_content = [
                "# Could not generate requirements automatically",
                "# Please install dependencies manually in enclave",
                f"# Error: {e}"
            ]

        # Get script metadata
        script_name = os.path.splitext(os.path.basename(analysis_script))[0]
        analysis_name = script_name.replace('_', ' ').title()

        # Build manifest
        manifest = {
            'version': '1.0',
            'analysis': {
                'name': analysis_name,
                'description': f'Analysis from {os.path.basename(analysis_script)}',
                'script_file': os.path.basename(analysis_script),  # Use original script name
                'requirements': 'requirements.txt'
            },
            'datasets': datasets,
            'privacy': {
                'epsilon': 1.0
            },
            'execution': {
                'environment': 'enclave',
                'timeout': 300
            },
            'generated_at': str(datetime.now()),
            'build_info': {
                'command': f'epsilon build {analysis_script}',
                'detected_datasets': len(datasets),
                'original_script': analysis_script
            }
        }

        # Create output files
        yaml_file = os.path.join(output_dir, 'build.yml')
        python_file = os.path.join(output_dir, f'{script_name}.py')
        requirements_file = os.path.join(output_dir, 'requirements.txt')
        # Step 1: Write YAML manifest
        with open(yaml_file, 'w') as f:
            yaml.dump(manifest, f, default_flow_style=False, indent=2, sort_keys=False)

        # Step 2: Copy Python script
        shutil.copy2(analysis_script, python_file)
        print(f"Copied {analysis_script}")

        # Step 3: Create requirements.txt
        with open(requirements_file, 'w') as f:
            f.write('\n'.join(requirements_content))

        typer.secho(f"Analysis package built successfully!", fg=typer.colors.GREEN)

        # Show what was created
        print(f"\n Build Package Created: {output_dir}/")
        print(f"   build.yml - Analysis manifest")
        print(f"   {script_name}.py - Analysis script")

        # Show summary
        print(f"\nPackage Summary:")
        print(f"   Analysis: {manifest['analysis']['name']}")
        print(f"   Script: {manifest['analysis']['script_file']}")

        print(f"   Dataset: {dataset_id} (archetype: {archetype_id})")
        print(f"   Import: from generated.models import create_dataset")

        print(f"\n Ready for Server:")
        print(f"   1. Submit package: {output_dir}/")
        print(f"   2. Server reads: build.yml")
        print(f"   3. Server executes: {script_name}.py")

        # Auto add build folder to git
        try:
            subprocess.run(['git', 'add', output_dir], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            pass  # Not a git repo or git not available
        except FileNotFoundError:
            pass  # git not installed

        return output_dir

    except typer.Exit:
        raise
    except Exception as e:
        typer.secho(f" Build failed: {e}", fg=typer.colors.RED)
        traceback.print_exc()
        raise typer.Exit(1)


@app.command()
def version():
    """
    Show the current version of epsilon-sdk.
    """
    try:
        from sdk.__version__ import __version__
        typer.echo(__version__)
    except ImportError:
        typer.echo("Version information not available")


if __name__ == "__main__":
    app()
