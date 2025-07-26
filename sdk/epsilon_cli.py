import subprocess
import sys

import typer
import json
import os
import configparser
import requests
from pathlib import Path
from datetime import datetime
import importlib.util
import yaml
from sdk.auth import Auth, AuthenticationError
from sdk.archetype import compile_archetype as compile_arch

from sdk.mock_data import get_mock_datasets, get_mock_archetype, get_available_mock_dataset_ids


app = typer.Typer(
    help="CLI for epsilon SDK: working with datasets, authentication, and generating Python model classes.")

# Configuration directory and file paths
CONFIG_DIR = Path.home() / ".epsilon_sdk"
CONFIG_PATH = CONFIG_DIR / "credentials.ini"

isMock = True

def get_config(profile: str = "default") -> dict:
    """Get configuration for the given profile."""
    if not CONFIG_PATH.exists():
        typer.secho("🔒 No credentials found. Please run `epsilon login` first.", fg=typer.colors.RED)
        raise typer.Exit(1)

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if profile not in config:
        typer.secho(f"🔒 Profile '{profile}' not found. Available profiles: {', '.join(config.sections())}",
                    fg=typer.colors.RED)
        raise typer.Exit(1)

    return dict(config[profile])


def make_authenticated_request(method: str, endpoint: str, profile: str = "default", **kwargs):
    """Make an authenticated request to the API."""
    config = get_config(profile)
    access_token = config.get("access_token")
    base_url = config.get("base_url")

    if not access_token:
        typer.secho("No access token found. Please run `epsilon login` first.", fg=typer.colors.RED)
        raise typer.Exit(1)

    # Check token expiration
    expires_at_str = config.get('expires_at')
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now() >= expires_at:
            typer.secho("Access token has expired. Please run `epsilon login` again.", fg=typer.colors.RED)
            raise typer.Exit(1)

    # Build the full URL and make request
    full_url = f"{base_url}{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.request(method, full_url, headers=headers, **kwargs)
    response.raise_for_status()
    return response


@app.command()
def login(
        username: str = typer.Option(..., prompt=True, help="Your username or email."),
        password: str = typer.Option(..., prompt=True, hide_input=True, help="Your password."),
        base_url: str = typer.Option("http://localhost:3000", help="Base URL for all Epsilon APIs."),
        profile: str = typer.Option("default", help="Profile name to store credentials under.")
):
    """
    Authenticate with Keycloak and store access token locally.
    """
    try:
        # Construct the auth URL from base URL
        auth_url = f"{base_url}/realms/EPSILON/protocol/openid-connect/token"

        typer.echo("Authenticating with Keycloak...")

        if isMock:
            # Mock authentication for testing purposes
            auth = Auth(access_token="mock_access_token")
        else:
            auth = Auth.authenticate_with_keycloak(
                username=username,
                password=password,
                auth_url=auth_url
            )

        # Store the credentials and configuration
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config = configparser.ConfigParser()
        if CONFIG_PATH.exists():
            config.read(CONFIG_PATH)

        config[profile] = {
            "access_token": auth.access_token,
            "expires_at": auth.token_expires_at.isoformat() if auth.token_expires_at else "",
            "base_url": base_url,
            "username": username
        }

        with open(CONFIG_PATH, "w") as f:
            config.write(f)

        typer.secho(f"Successfully authenticated! Using base URL: {base_url}", fg=typer.colors.GREEN)

        # Show token expiration time
        if auth.token_expires_at:
            typer.echo(f"Token expires at: {auth.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

    except AuthenticationError as e:
        typer.secho(f"Authentication failed: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"Unexpected error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def status(
        profile: str = typer.Option("default", help="Profile name to check status for.")
):
    """
    Check the authentication status and token validity.
    """
    try:
        config = get_config(profile)

        typer.secho(f"Profile: {profile}", fg=typer.colors.BLUE)
        typer.echo(f"Base URL: {config.get('base_url', 'N/A')}")
        typer.echo(f"Username: {config.get('username', 'N/A')}")

        # Check token expiration
        expires_at_str = config.get('expires_at')
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            now = datetime.now()

            if now >= expires_at:
                typer.secho(f"Token expired at: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}", fg=typer.colors.RED)
                typer.echo("Please run 'epsilon login' to refresh your authentication.")
            else:
                time_left = expires_at - now
                typer.secho(f"Token valid until: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}", fg=typer.colors.GREEN)
                typer.echo(f"Time remaining: {time_left}")
        else:
            typer.echo("No expiration info available")

    except Exception as e:
        typer.secho(f"Error checking status: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def datasets(
        profile: str = typer.Option("default", help="Profile name to use for authentication.")
):
    """
    List available datasets from the Epsilon API.
    """
    try:
        if isMock:
            # Use mock data
            mock_datasets = get_mock_datasets()

            typer.secho("[MOCK MODE] Available datasets:", fg=typer.colors.BLUE)
            for idx, dataset in enumerate(mock_datasets, 1):
                typer.echo(f"{idx}. ID: {dataset['id']} - {dataset['name']}")
                typer.echo(f"   Description: {dataset['description']}")
                typer.echo("")

            typer.secho("Try: epsilon archetypes <dataset_id>", fg=typer.colors.YELLOW)
            return

        # Real API call
        response = make_authenticated_request("GET", "/api/datasets", profile)
        datasets = response.json()

        typer.secho("Available datasets:", fg=typer.colors.BLUE)
        for idx, dataset in enumerate(datasets, 1):
            typer.echo(f"{idx}. ID: {dataset.get('id', 'N/A')} - {dataset.get('name', 'Unnamed')}")
            if "description" in dataset and dataset["description"]:
                typer.echo(f"   Description: {dataset['description']}")
            typer.echo("")

    except Exception as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def archetypes(
        dataset_id: str = typer.Argument(..., help="ID of the dataset to download archetype from."),
        out_dir: str = typer.Option("archetypes", help="Base directory to save archetypes."),
        profile: str = typer.Option("default", help="Profile name to use for authentication.")
):
    """
    Download archetype from a specified dataset and generate CSV dummy data.
    Creates organized folder structure: archetypes/<dataset_id>/
    """
    try:
        if isMock:
            # Use mock data
            archetype_data = get_mock_archetype(dataset_id)

            if archetype_data is None:
                available_ids = get_available_mock_dataset_ids()
                typer.secho(f"Dataset '{dataset_id}' not found in mock data", fg=typer.colors.RED)
                typer.secho(f"Available datasets: {', '.join(available_ids)}", fg=typer.colors.YELLOW)
                raise typer.Exit(1)

            typer.secho(f"[MOCK MODE] Using mock archetype for {dataset_id}", fg=typer.colors.YELLOW)
        else:
            # Real API call
            response = make_authenticated_request("GET", f"/api/datasets/{dataset_id}/archetype", profile)
            archetype_data = response.json()

        # Create organized directory structure: archetypes/<dataset_id>/
        dataset_dir = os.path.join(out_dir, dataset_id)
        os.makedirs(dataset_dir, exist_ok=True)

        # Save the archetype to file in dataset folder
        archetype_file = os.path.join(dataset_dir, f"{dataset_id}.json")
        with open(archetype_file, 'w') as f:
            json.dump(archetype_data, f, indent=2)

        typer.secho(f"Archetype downloaded to {archetype_file}", fg=typer.colors.GREEN)

        # Generate CSV dummy data in dataset folder
        print("Generating CSV dummy data...")
        from sdk.archetype import generate_csv_dummy_data

        csv_file = os.path.join(dataset_dir, f"{dataset_id}_dummy.csv")
        generate_csv_dummy_data(archetype_data, csv_file, num_records=10)

        typer.secho(f"Dummy data generated: {csv_file}", fg=typer.colors.GREEN)

        # Update compile command suggestion
        print(f"You can compile it using: epsilon compile {archetype_file}")

    except Exception as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def compile(
        archetype_file: str = typer.Argument(..., help="Path to the archetype JSON file."),
        out_file: str = typer.Option(None, help="Path to save the generated Python models.")
):
    """
    Compile a JSON archetype into Python classes.
    """
    try:
        if not out_file:
            # Use the same name as the archetype file but with .py extension
            out_file = os.path.splitext(archetype_file)[0] + ".py"

        # Use the existing compile_arch import (no changes needed here)
        output_path = compile_arch(archetype_file, out_file)
        typer.secho(f"Model classes generated at {output_path}", fg=typer.colors.GREEN)

        # Show example usage
        basename = os.path.basename(output_path)
        module_name = os.path.splitext(basename)[0]
        typer.echo("\nExample usage:")
        typer.echo(f"  from {module_name} import create_dataset")
        typer.echo("  dataset = create_dataset()")

        # Parse the archetype to show example access
        with open(archetype_file, 'r') as f:
            data = json.load(f)

        if data:
            # Find the first key in the data for example
            first_key = next(iter(data))
            typer.echo(f"  # Access with dot notation:")
            typer.echo(f"  dataset.first.{first_key}")

            # If there's a nested structure, show that as an example too
            if isinstance(data[first_key], dict):
                nested_key = next(iter(data[first_key]))
                typer.echo(f"  dataset.first.{first_key}.{nested_key}")

    except Exception as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def build(
        analysis_script: str = typer.Argument(..., help="Path to analysis script"),
        output_dir: str = typer.Option("./build", help="Output directory")
):
    """
    Build analysis package by analyzing import statements in Python script.
    Creates both YAML manifest and prepared Python script in build directory.
    """
    try:
        import ast
        import shutil

        os.makedirs(output_dir, exist_ok=True)

        print(f"Building analysis package from: {analysis_script}")

        if not os.path.exists(analysis_script):
            typer.secho(f"Script not found: {analysis_script}", fg=typer.colors.RED)
            raise typer.Exit(1)

        # Parse the Python script
        with open(analysis_script, 'r') as f:
            source = f.read()

        tree = ast.parse(source)

        # Find dataset imports
        datasets = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module

                # Look for: from archetypes.dataset_name.dataset_name import create_dataset
                if (module and
                        module.startswith('archetypes.') and
                        '.create_dataset' not in module):

                    # Extract dataset name from module path
                    # archetypes.customer_db.customer_db -> customer_db
                    parts = module.split('.')
                    if len(parts) >= 3 and parts[0] == 'archetypes':
                        dataset_id = parts[1]  # customer_db, sales_db, etc.

                        # Check if importing create_dataset
                        imports_create_dataset = any(
                            alias.name == 'create_dataset'
                            for alias in (node.names or [])
                        )

                        if imports_create_dataset:
                            # Get the alias name if any
                            alias_name = None
                            for alias in node.names:
                                if alias.name == 'create_dataset':
                                    alias_name = alias.asname or 'create_dataset'
                                    break

                            datasets.append({
                                'dataset_id': dataset_id,
                                'import_path': module,
                                'function_name': alias_name,
                                'archetype_path': f'archetypes/{dataset_id}/{dataset_id}.json'
                            })

                            print(f"Found dataset: {dataset_id}")

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

                        # Count packages
                        package_count = len([line for line in pip_freeze_output.split('\n') if
                                             line.strip() and not line.startswith('#')])

                        print(f"Captured {package_count} packages from current environment")
                    else:
                        requirements_content = [
                            "# No packages found in current environment",
                            f"# Generated at: {datetime.now()}"
                        ]
                        package_count = 0
                        print("No packages found in current environment")

                except subprocess.CalledProcessError as e:
                    print(f"Could not run pip freeze: {e}")
                    requirements_content = [
                        "# Could not generate requirements automatically",
                        "# Please install dependencies manually in enclave",
                        f"# Error: {e}"
                    ]
                    package_count = 0

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
        yaml_file = os.path.join(output_dir, f'{script_name}.yml')
        python_file = os.path.join(output_dir, f'{script_name}.py')
        requirements_file = os.path.join(output_dir, 'requirements.txt')
        # Step 1: Write YAML manifest
        with open(yaml_file, 'w') as f:
            yaml.dump(manifest, f, default_flow_style=False, indent=2, sort_keys=False)

        # Step 2: Copy Python script to build directory
        shutil.copy2(analysis_script, python_file)
        
        # Step 2.5: Copy archetype files to build directory
        for dataset in datasets:
            archetype_path = dataset['archetype_path']
            if os.path.exists(archetype_path):
                # Create archetypes directory structure in build
                build_archetype_dir = os.path.join(output_dir, os.path.dirname(archetype_path))
                os.makedirs(build_archetype_dir, exist_ok=True)
                
                # Copy archetype files
                dataset_id = dataset['dataset_id']
                archetype_source_dir = os.path.dirname(archetype_path)
                build_archetype_target = os.path.join(output_dir, archetype_source_dir)
                
                # Copy all files from archetype directory
                if os.path.exists(archetype_source_dir):
                    shutil.copytree(archetype_source_dir, build_archetype_target, dirs_exist_ok=True)
                    print(f"Copied archetype files for {dataset_id} to build directory")

        # Step 3: Create requirements.txt using pip freeze
        with open(requirements_file, 'w') as f:
            f.write('\n'.join(requirements_content))

        typer.secho(f"Analysis package built successfully!", fg=typer.colors.GREEN)

        # Show what was created
        print(f"\n Build Package Created: {output_dir}/")
        print(f"   {script_name}.yml - Analysis manifest")
        print(f"   {script_name}.py - Analysis script")

        # Show summary
        print(f"\nPackage Summary:")
        print(f"   Analysis: {manifest['analysis']['name']}")
        print(f"   Script: {manifest['analysis']['script_file']}")

        if datasets:
            print(f"   Datasets ({len(datasets)}):")
            for dataset in datasets:
                print(f"{dataset['dataset_id']} → {dataset['function_name']}()")
        else:
            typer.secho("No datasets detected!", fg=typer.colors.YELLOW)

        print(f"\n Ready for Server:")
        print(f"   1. Submit package: {output_dir}/")
        print(f"   2. Server reads: {script_name}.yml")
        print(f"   3. Server executes: {script_name}.py")
        return output_dir

    except Exception as e:
        typer.secho(f" Build failed: {e}", fg=typer.colors.RED)
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)

if __name__ == "__main__":
    app()