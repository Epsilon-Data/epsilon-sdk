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
from . import config as sdk_config
from .credentials import credentials_path
from sdk import profile as profile_mod
from sdk import catalogue as catalogue_mod
from sdk import checks as checks_mod
from sdk import explain as explain_mod
from sdk import snippets as snippets_mod
import re
import shutil
import traceback
import tempfile

app = typer.Typer(
    help="CLI for epsilon SDK: working with datasets, authentication, and generating Python model classes.")

# Configuration directory and file paths
CONFIG_PATH = credentials_path()


def get_client() -> APIClient:
    """Get API client with stored credentials."""
    return APIClient.from_config(CONFIG_PATH)


@app.command()
def login(
        username: str = typer.Option(..., prompt=True, help="Your username or email."),
        password: str = typer.Option(..., prompt=True, hide_input=True, help="Your password."),
):
    """Sign in with Epsilon credentials and store the access token locally."""
    from sdk.credentials import sign_in
    try:
        typer.echo("Authenticating with Epsilon...")
        client = sign_in(username, password, path=CONFIG_PATH, client_factory=APIClient)
        if client.token_expires_at:
            typer.echo("Token expires at: " + client.token_expires_at.strftime("%Y-%m-%d %H:%M:%S"))
        typer.echo("Success")
    except AuthenticationError as exc:
        typer.secho("Authentication failed: " + str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as exc:
        typer.secho("Unexpected error: " + str(exc), fg=typer.colors.RED)
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


@app.command()
def doctor():
    """Check local project, login and notebook prerequisites without changing anything."""
    checks = []
    blockers = 0

    if CONFIG_PATH.exists():
        config = configparser.ConfigParser()
        config.read(CONFIG_PATH)
        if "default" in config and config["default"].get("access_token"):
            checks.append(("Account", "ok", "credentials are stored locally"))
        else:
            checks.append(("Account", "action", "run 'epsilon login' to save credentials"))
            blockers += 1
    else:
        checks.append(("Account", "action", "run 'epsilon login' to save credentials"))
        blockers += 1

    project_file = Path("project.yml")
    if not project_file.exists():
        checks.append(("Project", "info", "no project.yml in this folder; run 'epsilon init <dataset_id>'"))
    else:
        try:
            project = yaml.safe_load(project_file.read_text()) or {}
            if not isinstance(project, dict):
                raise ValueError("project.yml must contain a mapping")
            entry_point = project.get("entry_point", "main.py")
            missing = [name for name in (entry_point, "generated/archetype.json", "generated/data.csv")
                       if not Path(name).is_file()]
            if missing:
                checks.append(("Project", "action", "missing " + ", ".join(missing)))
                blockers += 1
            else:
                checks.append(("Project", "ok", f"{entry_point} and generated projection are present"))
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            checks.append(("Project", "action", "project.yml could not be read: " + str(exc)))
            blockers += 1

    docker = shutil.which("docker")
    if not docker:
        checks.append(("Notebook", "optional", "Docker is not installed; editing and AI remain available, cell execution does not"))
    else:
        try:
            daemon = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                                    capture_output=True, text=True, timeout=5,
                                    env={key: value for key, value in os.environ.items()
                                         if key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG",
                                                    "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY", "SYSTEMROOT", "USERPROFILE")})
            if daemon.returncode:
                checks.append(("Docker", "action", "the Docker daemon is not running; start Docker and retry"))
            else:
                image = subprocess.run([docker, "image", "inspect", "epsilon-notebook:local", "--format", "{{.Id}}"],
                                       capture_output=True, text=True, timeout=5)
                if image.returncode or not image.stdout.strip().startswith("sha256:"):
                    checks.append(("Notebook", "action", "Docker is ready; run 'epsilon notebook-build' once"))
                else:
                    checks.append(("Notebook", "ok", "Docker and the isolated notebook image are ready"))
        except (OSError, subprocess.TimeoutExpired):
            checks.append(("Docker", "action", "Docker could not be queried; start it and retry"))

    typer.secho("Epsilon doctor", fg=typer.colors.BLUE, bold=True)
    symbols = {"ok": ("✓", typer.colors.GREEN), "action": ("!", typer.colors.YELLOW),
               "optional": ("·", typer.colors.BRIGHT_BLACK), "info": ("·", typer.colors.BRIGHT_BLACK)}
    for label, status_code, detail in checks:
        symbol, colour = symbols[status_code]
        typer.secho(f"{symbol} {label}: ", fg=colour, nl=False)
        typer.echo(detail)
    if blockers:
        raise typer.Exit(1)


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

    url = url.rstrip('/')
    try:
        # Saved in the user's state folder: the installed package may be
        # read-only, and an upgrade would silently replace an edited file.
        where = sdk_config.save_server(url)
    except OSError as e:
        typer.secho(f"Failed to update server: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    sdk_config.BASE_URL = url
    typer.secho(f"Server updated to: {url}", fg=typer.colors.GREEN)
    typer.echo(f"Saved in {where}")
    if os.environ.get("EPSILON_SERVER_URL"):
        typer.secho("EPSILON_SERVER_URL is set in this shell and takes precedence over the saved server.",
                    fg=typer.colors.YELLOW)
    typer.echo("Note: You'll need to login again with 'epsilon login'")


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
            last_modified = dataset.get('lastModified', '')
            status = dataset.get('status', '')

            typer.echo(f"{idx}. Dataset ID: {dataset_id}")
            if dataset.get('name'):
                typer.echo(f"   Name: {dataset['name']}")
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
                                       help="Generate random dummy data instead of downloading the synthetic dataset.")
):
    """Initialise a project using the same service as the browser workspace."""
    from sdk.project_setup import initialise_project
    try:
        if Path("project.yml").exists():
            raise SDKError("Project already initialized. Choose a new project folder.")
        typer.secho("Initializing project with dataset: " + dataset_id, fg=typer.colors.BLUE)
        result = initialise_project(".", dataset_id, get_client(), dummy_data,
                                    lambda stage, message: typer.echo(message))
        if result["source"] == "dummy":
            typer.echo("Generating random dummy data (--dummy-data)..." if dummy_data else
                       "No synthetic dataset attached to this dataset — generating dummy data.")
        for warning in result["warnings"]:
            typer.secho("Warning: " + warning, fg=typer.colors.YELLOW)
        project = result["project"]
        detail = "synthetic dataset" if result["source"] == "synthetic" else ("random dummy data" if dummy_data else "dummy data")
        if project.get("schema_hash"):
            detail += ", schema " + str(project["schema_hash"])[:12]
        if project.get("dataset_version") is not None:
            detail += ", version " + str(project["dataset_version"])
        for name in ("__init__.py", "archetype.json", "models.py"):
            typer.secho("✓ Created generated/" + name, fg=typer.colors.GREEN)
        typer.secho("✓ Created generated/data.csv (" + detail + ")", fg=typer.colors.GREEN)
        typer.secho("✓ Created project.yml", fg=typer.colors.GREEN)
        typer.secho("✓ Created main.py template (or preserved existing entry point)", fg=typer.colors.GREEN)
        typer.secho("✓ Created .gitignore (or preserved existing rules)", fg=typer.colors.GREEN)
        typer.secho("Project initialized successfully!", fg=typer.colors.GREEN)
        typer.echo("Run 'epsilon start' to explore the project in your browser.")
    except (SDKError, ValueError, OSError) as exc:
        typer.secho("Initialization failed: " + str(exc), fg=typer.colors.RED)
        if not dummy_data:
            typer.echo("For random development data, use 'epsilon init " + dataset_id + " --dummy-data'.")
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
def clean(
        yes: bool = typer.Option(False, "--yes", "-y", help="Delete without asking for confirmation.")
):
    """
    Clean project files (generated/ folder, main.py, project.yml).
    """

    files_to_clean = ["project.yml", "main.py", ".gitignore"]
    dirs_to_clean = ["generated", "build"]

    present = ([f for f in files_to_clean if os.path.exists(f)] +
               [f"{d}/" for d in dirs_to_clean if os.path.exists(d)])
    if not present:
        typer.echo("No project files to clean")
        return
    # main.py holds the researcher's own analysis code.
    if not yes and not typer.confirm(f"Delete {', '.join(present)} from {os.getcwd()}?", default=False):
        typer.echo("Nothing was deleted.")
        raise typer.Exit(1)

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


def _run_submission_checks(analysis_script):
    """Print every finding; stop the build if any of them blocks submission."""
    findings = checks_mod.check_project(".")
    findings.extend(checks_mod.check_packaging(".", analysis_script, set(PACKAGED_DIRS)))
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


def _copy_packaged_dirs(output_dir):
    print("Copying generated files...")
    if os.path.exists("generated"):
        shutil.copytree("generated", os.path.join(output_dir, "generated"), dirs_exist_ok=True)
        print("Copied generated/ folder")
    # Analyses written by 'epsilon snippet' live here and are imported by
    # the entry point, so they have to travel with it.
    if os.path.exists(PACKAGED_DIRS[1]):
        shutil.copytree(PACKAGED_DIRS[1], os.path.join(output_dir, PACKAGED_DIRS[1]), dirs_exist_ok=True)
        print("Copied {0}/ folder".format(PACKAGED_DIRS[1]))


def _requirements(analysis_script):
    """requirements.txt lines, from pip freeze of the current environment."""
    print("Generating requirements.txt...")
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', 'freeze'],
                                capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Could not run pip freeze: {e}")
        return ["# Could not generate requirements automatically",
                "# Please install dependencies manually in enclave",
                f"# Error: {e}"]
    frozen = result.stdout.strip()
    if not frozen:
        print("No packages found in current environment")
        return ["# No packages found in current environment", f"# Generated at: {datetime.now()}"]
    print(f"Captured {len([line for line in frozen.split() if line.strip()])} packages")
    return ["# Auto-generated requirements using pip freeze",
            f"# Generated from: {analysis_script}",
            f"# Generated at: {datetime.now()}",
            "",
            frozen]


def _manifest(analysis_script, dataset_id, archetype_id):
    """The build.yml the coordinator reads."""
    datasets = [{
        'dataset_id': dataset_id,
        'archetype_id': archetype_id,
        'import_path': 'generated.models',
        'function_name': 'create_dataset',
        'archetype_path': 'generated/archetype.json'
    }]
    script_name = os.path.splitext(os.path.basename(analysis_script))[0]
    return {
        'version': '1.0',
        'analysis': {
            'name': script_name.replace('_', ' ').title(),
            'description': f'Analysis from {os.path.basename(analysis_script)}',
            'script_file': os.path.basename(analysis_script),
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


def _write_package(output_dir, analysis_script, manifest, requirements):
    script_name = os.path.splitext(os.path.basename(analysis_script))[0]
    with open(os.path.join(output_dir, 'build.yml'), 'w') as f:
        yaml.dump(manifest, f, default_flow_style=False, indent=2, sort_keys=False)
    shutil.copy2(analysis_script, os.path.join(output_dir, f'{script_name}.py'))
    print(f"Copied {analysis_script}")
    with open(os.path.join(output_dir, 'requirements.txt'), 'w') as f:
        f.write('\n'.join(requirements))
    return script_name


def _stage_in_git(output_dir):
    """The coordinator clones the project repository, so the package must be
    committed. Staging is announced and can be switched off."""
    try:
        subprocess.run(['git', 'add', output_dir], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return  # Not a git repository, or git is not installed
    print(f"\n📌 Staged {output_dir}/ in git. Commit and push it to submit "
          "(use --no-git-add to skip staging).")


@app.command()
def build(
        output_dir: str = typer.Option("./build", help="Output directory"),
        skip_checks: bool = typer.Option(
            False, "--skip-checks",
            help="Package without running the submission checks first."),
        git_add: bool = typer.Option(
            True, "--git-add/--no-git-add",
            help="Stage the package in git; the platform reads it from your repository.")
):
    """
    Build analysis package from project configuration.
    Reads project.yml to get entry point and dataset information.

    Runs the local submission checks first: the package is shipped to the
    coordinator, so a credential or a raw-record release found here is one that
    never leaves the machine.
    """
    try:
        if not os.path.exists("project.yml"):
            typer.secho("Error: Not in an Epsilon project directory.", fg=typer.colors.RED)
            typer.echo("Run 'epsilon init <dataset_id>' to create a project first.")
            raise typer.Exit(1)
        with open("project.yml", 'r') as f:
            project = yaml.safe_load(f)
        analysis_script = project.get('entry_point', 'main.py')
        dataset_id = project.get('dataset_id')
        archetype_id = project.get('archetype_id')

        if not skip_checks:
            _run_submission_checks(analysis_script)

        os.makedirs(output_dir, exist_ok=True)
        print(f"Building analysis package from: {analysis_script}")
        print(f"Dataset: {dataset_id} (archetype: {archetype_id})")
        if not os.path.exists(analysis_script):
            typer.secho(f"Script not found: {analysis_script}", fg=typer.colors.RED)
            raise typer.Exit(1)
        print(f"Using dataset: {dataset_id} (archetype: {archetype_id})")

        _copy_packaged_dirs(output_dir)
        requirements = _requirements(analysis_script)
        manifest = _manifest(analysis_script, dataset_id, archetype_id)
        script_name = _write_package(output_dir, analysis_script, manifest, requirements)

        typer.secho("Analysis package built successfully!", fg=typer.colors.GREEN)
        print(f"\n Build Package Created: {output_dir}/")
        print("   build.yml - Analysis manifest")
        print(f"   {script_name}.py - Analysis script")
        print("\nPackage Summary:")
        print(f"   Analysis: {manifest['analysis']['name']}")
        print(f"   Script: {manifest['analysis']['script_file']}")
        print(f"   Dataset: {dataset_id} (archetype: {archetype_id})")
        print("   Import: from generated.models import create_dataset")
        print("\n Ready for Server:")
        print(f"   1. Submit package: {output_dir}/")
        print("   2. Server reads: build.yml")
        print(f"   3. Server executes: {script_name}.py")

        if git_add:
            _stage_in_git(output_dir)
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
    problem = ai_config.check_base_url(base_url)
    if problem:
        typer.secho(problem, fg=typer.colors.RED)
        raise typer.Exit(1)
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
            if ai_config.stored_key():
                typer.secho(
                    "           WARNING: {0} is shadowing a key stored in your "
                    "keyring.\n           Run 'unset {0}' to use the stored "
                    "one.".format(name), fg=typer.colors.YELLOW)
    else:
        typer.secho("key      : not found", fg=typer.colors.YELLOW)
        typer.echo("           run 'epsilon ai login', or set " + ", ".join(ai_config.ENV_KEYS))
    _report_workspace_ai(cfg)
    typer.echo("")
    typer.echo("explain, snippet and check work without a model.")


def _report_workspace_ai(cfg):
    """The workspace can save its own connection or model; say when it differs."""
    from sdk.workbench.store import read_setting
    database = Path.home() / sdk_config.CREDENTIALS_DIR / "workbench.db"
    own = read_setting(database, "ai")
    chosen = read_setting(database, "ai_model")
    active = own or {"provider": cfg.provider, "base_url": cfg.base_url, "model": cfg.model}
    model = active.get("model")
    if chosen and chosen.get("provider") == active.get("provider") and chosen.get("base_url") == active.get("base_url"):
        model = chosen.get("model") or model
    if not own and model == cfg.model:
        return
    typer.echo("")
    typer.secho("workspace: epsilon start uses {0}{1} / {2}, set in its Settings.".format(
        active.get("provider"), " at " + active["base_url"] if active.get("base_url") else "", model),
        fg=typer.colors.YELLOW)
    if own:
        typer.echo("           Choose 'Use existing epsilon ai login settings' there to use the values above.")


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
        port: int = typer.Option(sdk_config.DEFAULT_PORT, min=1, max=65535, help="Port to serve on."),
        no_browser: bool = typer.Option(
            False, "--no-browser", help="Do not open a browser."),
        no_record: bool = typer.Option(
            False, "--no-record", help="Disable the audit log; conversations still persist in the workspace database.")
):
    """
    Start the Epsilon workspace in a browser.

    Walks setup, shows what the dataset holds and what it can and cannot
    answer, and is where the assistant lives -- there is no terminal chat.
    Serves on loopback. Uses the existing epsilon login credentials.
    Defaults to https://app.epsilon-data.org and ~/.epsilon_sdk/credentials.ini,
    with username/password sign-in. No environment variables are required.
    Cloud AI receives permitted schema and conversation context when enabled.
    """
    from sdk.workbench import server as workbench_server
    if not workbench_server.available():
        typer.secho("The workspace dependencies are missing from this Python environment. Reinstall:",
                    fg=typer.colors.RED)
        typer.echo("  pip install --force-reinstall epsilon-sdk")
        raise typer.Exit(1)
    try:
        server, url = workbench_server.serve(".", port, open_browser=not no_browser, record=not no_record)
    except OSError as exc:
        import errno
        if exc.errno == errno.EADDRINUSE:
            _port_taken(port, no_browser)
        typer.secho("Cannot start the workspace. Check access to the SDK state directory and the local port.", fg=typer.colors.RED)
        raise typer.Exit(1)
    _announce(url, None, chat="local research workbench")
    typer.echo("  The launch link unlocks this browser once and expires after 10 minutes.")
    try:
        server.run()
    except KeyboardInterrupt:
        typer.echo("")


def _port_taken(port: int, no_browser: bool):
    """The port is busy. If it is an Epsilon workspace, point at it."""
    import urllib.request
    import webbrowser

    url = "http://127.0.0.1:{0}/".format(port)
    try:
        with urllib.request.urlopen(url + "api/health", timeout=2) as res:
            payload = json.load(res)
            if payload.get("application") != "epsilon-workbench":
                raise ValueError("Not an Epsilon workbench")
    except Exception:
        typer.secho("Port {0} is taken by something else.".format(port),
                    fg=typer.colors.RED)
        typer.echo("Try 'epsilon start --port {0}'.".format(port + 1))
        raise typer.Exit(1)
    typer.secho("epsilon workspace", bold=True)
    from sdk.workbench.server import existing_launch_url
    fresh = existing_launch_url(port)
    if fresh:
        url = fresh
    typer.echo("  already running at {0}".format(url))
    typer.secho("  Your running work is preserved. Open this fresh link within 10 minutes." if fresh else
                "  Stop it with Ctrl-C in its own terminal, then run epsilon start for a fresh launch link.",
                fg=typer.colors.BRIGHT_BLACK)
    if not no_browser:
        webbrowser.open(url)
    raise typer.Exit(0)


def _notebook_requirements(path: Path):
    """Read a researcher-owned package list without allowing shell/options/URLs."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SDKError("Notebook requirements file was not found: " + str(path))
    if path.stat().st_size > 20000:
        raise SDKError("Notebook requirements file is too large.")
    pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:\s*(?:==|~=|>=|<=|>|<)\s*[A-Za-z0-9.*+!-]+)?$")
    lines = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = raw.split("#", 1)[0].strip()
        if not value:
            continue
        if value.startswith(("-", "http:", "https:", "git+", "file:")) or not pattern.fullmatch(value):
            raise SDKError(f"Unsupported notebook requirement on line {number}. Use a package name with an optional version constraint.")
        lines.append(value)
    return lines


@app.command("notebook-build")
def notebook_build(
        requirements: Optional[Path] = typer.Option(None, "--requirements",
                                                     help="Optional project package list to add to the managed notebook image."),
):
    """Build the optional Docker image for isolated Python notebook execution."""
    from sdk.workbench.kernel import IMAGE, docker_environment
    docker = shutil.which("docker")
    if not docker:
        typer.secho("Install and start Docker, then run epsilon notebook-build again.", fg=typer.colors.RED)
        raise typer.Exit(1)
    context = Path(__file__).parent / "workbench" / "runtime"
    temporary = None
    if requirements:
        try:
            extra = _notebook_requirements(requirements)
        except (OSError, SDKError) as exc:
            typer.secho("Notebook requirements rejected: " + str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)
        temporary = tempfile.TemporaryDirectory(prefix="epsilon-notebook-build-")
        custom_context = Path(temporary.name) / "runtime"
        shutil.copytree(context, custom_context)
        managed = (custom_context / "requirements.txt").read_text(encoding="utf-8").rstrip()
        (custom_context / "requirements.txt").write_text(managed + ("\n" if managed else "") + "\n".join(extra) + "\n", encoding="utf-8")
        context = custom_context
        typer.echo("Adding " + ", ".join(extra) + " to the managed notebook image.")
    typer.echo("Building " + IMAGE + ". Docker downloads the Python base image and notebook dependencies.")
    try:
        result = subprocess.run([docker, "build", "--tag", IMAGE, str(context)], env=docker_environment())
    except OSError as exc:
        typer.secho("Could not start Docker: " + str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    finally:
        if temporary:
            temporary.cleanup()
    if result.returncode:
        typer.secho("Notebook runtime build failed. Check Docker and retry.", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo("Notebook runtime ready. Restart any running notebook from its options menu to use the updated libraries; saved source is preserved.")


def _announce(url, profile, chat: str) -> None:
    typer.secho("epsilon workspace", bold=True)
    typer.echo("  {0}".format(url))
    typer.secho("  {0} | {1}".format(
        profile.title if profile else "no project yet", chat),
        fg=typer.colors.BRIGHT_BLACK)
    typer.secho("  Ctrl-C to stop", fg=typer.colors.BRIGHT_BLACK)


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
