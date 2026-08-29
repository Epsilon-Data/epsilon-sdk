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
from typing import List, Optional
from datetime import datetime
import yaml
from .client import APIClient
from .errors import AuthenticationError, SDKError
from sdk.archetype import compile_archetype as compile_arch
from sdk.archetype import generate_csv_dummy_data
from sdk.archetype import verify_synthetic_csv
from . import config as sdk_config
from sdk import profile as profile_mod
from sdk import catalogue as catalogue_mod
from sdk import checks as checks_mod
from sdk import explain as explain_mod
from sdk import snippets as snippets_mod
from sdk import agent as agent_mod
from sdk import ui as ui_mod
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
        output_dir: str = typer.Option("./build", help="Output directory"),
        skip_checks: bool = typer.Option(
            False, "--skip-checks",
            help="Package without running the submission checks first.")
):
    """
    Build analysis package from project configuration.
    Reads project.yml to get entry point and dataset information.

    Runs the local submission checks first: the package is shipped to the
    coordinator, so a credential or a raw-record release found here is one that
    never leaves the machine.
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

        if not skip_checks:
            findings = checks_mod.check_project(".")
            findings.extend(checks_mod.check_packaging(
                ".", analysis_script, set(PACKAGED_DIRS)))
            blocking = [f for f in findings if f.blocking]
            for finding in findings:
                colour = typer.colors.RED if finding.blocking else typer.colors.YELLOW
                typer.secho(finding.format(), fg=colour)
            if blocking:
                typer.echo("")
                typer.secho(
                    "{0} Fix them, or pass --skip-checks to package anyway "
                    "(the coordinator will apply the same rules).".format(
                        checks_mod.summarise(findings)), fg=typer.colors.RED)
                raise typer.Exit(1)
            if findings:
                typer.echo("")
                typer.secho(checks_mod.summarise(findings), fg=typer.colors.YELLOW)
            else:
                typer.secho("\u2713 Submission checks passed", fg=typer.colors.GREEN)

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

        # Analyses written by 'epsilon snippet' live here and are imported by
        # the entry point, so they have to travel with it.
        if os.path.exists(PACKAGED_DIRS[1]):
            shutil.copytree(PACKAGED_DIRS[1],
                            os.path.join(output_dir, PACKAGED_DIRS[1]),
                            dirs_exist_ok=True)
            print("Copied {0}/ folder".format(PACKAGED_DIRS[1]))

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


# ---------------------------------------------------------------- copilot --

# Directories 'epsilon build' ships alongside the entry point.
PACKAGED_DIRS = ("generated", snippets_mod.ANALYSES_DIR)

ai_app = typer.Typer(help="Configure the model the copilot uses. The key is "
                          "yours: calls go from this machine straight to the "
                          "endpoint and Epsilon never sees your prompts.")
app.add_typer(ai_app, name="ai")


def _profile_project_or_exit():
    """Measure the project's dataset, failing with an actionable message."""
    try:
        return profile_mod.profile_project(".")
    except profile_mod.ProfileError as exc:
        typer.secho("Error: {0}".format(exc), fg=typer.colors.RED)
        raise typer.Exit(1)


@app.command()
def explain(
        brief: bool = typer.Option(
            False, "--brief", help="Dataset only, without the analysis list.")
):
    """
    Explain what this dataset holds and what can be computed from it.

    Measured from the local dataset. Needs no API key and makes no network call, and
    the feasibility verdicts are the same ones 'epsilon chat' works from.
    """
    profile = _profile_project_or_exit()
    if brief:
        typer.echo(explain_mod.render(profile))
    else:
        typer.echo(explain_mod.render_full(profile))


@app.command()
def snippet(
        analysis: str = typer.Argument(..., help="Catalogue key, e.g. 'describe'."),
        set_: Optional[List[str]] = typer.Option(
            None, "--set", metavar="NAME=FIELD",
            help="Choose a field, e.g. --set by=patient.gender. Repeatable."),
        chart: bool = typer.Option(
            False, "--chart",
            help="Also generate a chart() drawing the released result."),
        output: str = typer.Option(None, "--output", "-o", help="Filename under analyses/."),
        show: bool = typer.Option(False, "--show", help="Print the code instead of writing it.")
):
    """
    Generate starter analysis code for one catalogue entry.

    The skeleton is a fixed template parameterised from what was measured, so
    suppression and the unit of analysis are structural rather than advisory.

    Fields are chosen automatically; --set overrides one. Overrides are
    validated against the measurement and cannot make a blocked analysis available.
    """
    profile = _profile_project_or_exit()
    if analysis not in catalogue_mod.SPECS_BY_KEY:
        typer.secho("Unknown analysis '{0}'.".format(analysis), fg=typer.colors.RED)
        typer.echo("Available: " + ", ".join(sorted(catalogue_mod.SPECS_BY_KEY)))
        raise typer.Exit(1)

    choices = {}
    for item in (set_ or []):
        if "=" not in item:
            typer.secho("--set expects NAME=FIELD, got '{0}'.".format(item),
                        fg=typer.colors.RED)
            raise typer.Exit(1)
        name, _, path = item.partition("=")
        choices[name.strip()] = path.strip()

    match = catalogue_mod.SPECS_BY_KEY[analysis].evaluate(profile)
    if choices:
        try:
            match = catalogue_mod.override(profile, match, choices)
        except catalogue_mod.OverrideError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)
    if not match.feasible:
        typer.secho("'{0}' is not available for this dataset.".format(analysis),
                    fg=typer.colors.RED)
        for blocker in match.blockers:
            typer.echo("  " + blocker)
        if match.unlock:
            typer.echo("  " + match.unlock)
        raise typer.Exit(1)

    try:
        if show:
            typer.echo(snippets_mod.render(profile, match, chart=chart))
            return
        path = snippets_mod.write(profile, match, project_dir=".",
                                  filename=output, chart=chart)
    except snippets_mod.SnippetError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho("Wrote {0}".format(path), fg=typer.colors.GREEN)
    for warning in match.warnings:
        typer.secho("  note: " + warning, fg=typer.colors.YELLOW)


@app.command()
def check(
        strict: bool = typer.Option(
            False, "--strict", help="Treat warnings as blocking.")
):
    """
    Run the submission checks locally, before building.

    These are the deterministic rules the coordinator applies: no raw records
    released, no network, no subprocesses, dependencies pinned, no credentials
    in the packaged tree.
    """
    findings = checks_mod.check_project(".")
    if os.path.exists("project.yml"):
        try:
            with open("project.yml", 'r') as f:
                entry = (yaml.safe_load(f) or {}).get('entry_point', 'main.py')
            findings.extend(checks_mod.check_packaging(
                ".", entry, set(PACKAGED_DIRS)))
        except (yaml.YAMLError, OSError):
            pass
    blocking = [f for f in findings if f.blocking]

    for finding in findings:
        colour = typer.colors.RED if finding.blocking else typer.colors.YELLOW
        typer.secho(finding.format(), fg=colour)

    if not findings:
        typer.secho("All checks passed.", fg=typer.colors.GREEN)
        return

    typer.echo("")
    typer.echo(checks_mod.summarise(findings))
    if blocking or (strict and findings):
        raise typer.Exit(1)


@ai_app.command("login")
def ai_login(
        provider: str = typer.Option(None, help="anthropic | openai-compatible"),
        model: str = typer.Option(None, help="Model identifier."),
        base_url: str = typer.Option(None, help="Endpoint base URL, for self-hosted models."),
        tier: str = typer.Option(None, help="Capability tier: A, B or C.")
):
    """
    Store the model settings, and the API key in this machine's keyring.

    The key is never written into a project directory: 'epsilon build'
    packages the project and ships it, so a key there would be an exfiltrated
    credential.
    """
    from sdk.llm import config as ai_config

    current = ai_config.load(include_key=False)
    provider = provider or typer.prompt("Provider", default=current.provider)
    if provider not in ai_config.PROVIDERS:
        typer.secho("Provider must be one of: {0}".format(", ".join(ai_config.PROVIDERS)),
                    fg=typer.colors.RED)
        raise typer.Exit(1)

    default_model = current.model or ai_config.DEFAULT_MODELS.get(provider, "")
    model = model or typer.prompt("Model", default=default_model)
    if base_url is None and provider == ai_config.PROVIDER_OPENAI_COMPATIBLE:
        base_url = typer.prompt("Base URL (e.g. http://localhost:11434/v1)",
                                default=current.base_url or "")
    tier = tier or typer.prompt("Capability tier (A/B/C)", default=current.tier)
    if tier not in (ai_config.TIER_A, ai_config.TIER_B, ai_config.TIER_C):
        typer.secho("Tier must be A, B or C.", fg=typer.colors.RED)
        raise typer.Exit(1)

    path = ai_config.save(provider, model, base_url, tier)
    typer.secho("Settings written to {0}".format(path), fg=typer.colors.GREEN)

    api_key = typer.prompt("API key (leave blank to use an environment variable)",
                           default="", hide_input=True)
    if api_key:
        where = ai_config.store_key(api_key)
        if where == "keyring":
            typer.secho("Key stored in this machine's keyring.", fg=typer.colors.GREEN)
        else:
            typer.secho(
                "No keyring is available on this machine, so the key was NOT "
                "saved. Export it instead:\n  export ANTHROPIC_API_KEY=...\n"
                "or install the optional 'keyring' package.",
                fg=typer.colors.YELLOW)
    else:
        typer.echo("No key stored. Set one of: " + ", ".join(ai_config.ENV_KEYS))


@ai_app.command("status")
def ai_status():
    """Show which model is configured and where its key comes from."""
    from sdk.llm import config as ai_config

    cfg = ai_config.load()
    typer.echo("provider : {0}".format(cfg.provider))
    typer.echo("model    : {0}".format(cfg.model or "(unset)"))
    typer.echo("base_url : {0}".format(cfg.base_url or "(default)"))
    typer.echo("tier     : {0}".format(cfg.tier))
    if cfg.api_key:
        typer.secho("key      : found via {0}".format(cfg.key_source),
                    fg=typer.colors.GREEN)
        # An environment variable outranks the keyring, so one left over from a
        # different endpoint silently sends the wrong credential.
        if (cfg.key_source or "").startswith("env:"):
            name = cfg.key_source.split(":", 1)[1]
            if ai_config._key_from_keyring():
                typer.secho(
                    "           WARNING: {0} is shadowing a key stored in your "
                    "keyring.\n           Run 'unset {0}' to use the stored "
                    "one.".format(name), fg=typer.colors.YELLOW)
    else:
        typer.secho("key      : not found", fg=typer.colors.YELLOW)
        typer.echo("           run 'epsilon ai login', or set " + ", ".join(ai_config.ENV_KEYS))
    typer.echo("")
    typer.echo("explain, snippet and check work without a model.")


@ai_app.command("logout")
def ai_logout():
    """Remove the stored API key from this machine's keyring."""
    from sdk.llm import config as ai_config

    if ai_config.delete_key():
        typer.secho("Key removed from the keyring.", fg=typer.colors.GREEN)
    else:
        typer.secho("No key was stored in the keyring.", fg=typer.colors.YELLOW)
    for name in ai_config.ENV_KEYS:
        if os.environ.get(name):
            typer.secho("Note: {0} is still set in this shell.".format(name),
                        fg=typer.colors.YELLOW)


@app.command()
def start(
        port: int = typer.Option(ui_mod.DEFAULT_PORT, help="Port to serve on."),
        no_browser: bool = typer.Option(
            False, "--no-browser", help="Do not open a browser."),
        no_record: bool = typer.Option(
            False, "--no-record", help="Do not write a chat transcript.")
):
    """
    Start the Epsilon workspace in a browser.

    Walks setup, shows what the dataset holds and what it can and cannot
    answer, and is where the assistant lives -- there is no terminal chat.
    Serves on loopback only, beside your project, so the data and your key
    never leave this machine.
    """
    # `start` must work before `init` -- guiding setup is half its job.
    try:
        profile = profile_mod.profile_project(".")
    except profile_mod.ProfileError:
        profile = None

    session = None
    try:
        from sdk import llm
        if profile is not None and llm.available():
            provider = llm.get_provider(llm.TIER_A, "the copilot agent")
            session = agent_mod.Session.create(
                provider, profile, project_dir=".", record=not no_record)
    except Exception as exc:
        typer.secho("Chat disabled: {0}".format(exc), fg=typer.colors.YELLOW)

    try:
        server, url = ui_mod.serve(profile, ".", session, port,
                                   open_browser=not no_browser)
    except OSError as exc:
        typer.secho("Could not start on port {0}: {1}".format(port, exc),
                    fg=typer.colors.RED)
        typer.echo("Try 'epsilon ui --port 8788'.")
        raise typer.Exit(1)

    typer.secho("epsilon workspace", bold=True)
    typer.echo("  {0}".format(url))
    typer.secho("  {0} | {1}".format(
        profile.title if profile else "no project yet",
        "assistant ready" if session else "assistant needs 'epsilon ai login'"),
        fg=typer.colors.BRIGHT_BLACK)
    typer.secho("  Ctrl-C to stop", fg=typer.colors.BRIGHT_BLACK)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("")
    finally:
        server.server_close()


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
