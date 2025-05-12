import typer
import json
import os
import configparser
import requests
from pathlib import Path
from datetime import datetime

from sdk.auth import Auth, AuthenticationError
from sdk.archetype import compile_archetype as compile_arch

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

        typer.secho(f"✅ Successfully authenticated! Using base URL: {base_url}", fg=typer.colors.GREEN)

        # Show token expiration time
        if auth.token_expires_at:
            typer.echo(f"Token expires at: {auth.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

    except AuthenticationError as e:
        typer.secho(f"❌ Authentication failed: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"❌ Unexpected error: {str(e)}", fg=typer.colors.RED)
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
                typer.secho(f"❌ Token expired at: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}", fg=typer.colors.RED)
                typer.echo("Please run 'epsilon login' to refresh your authentication.")
            else:
                time_left = expires_at - now
                typer.secho(f"✅ Token valid until: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}", fg=typer.colors.GREEN)
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
        out_dir: str = typer.Option("archetypes", help="Directory to save the archetype to."),
        profile: str = typer.Option("default", help="Profile name to use for authentication.")
):
    """
    Download archetype from a specified dataset.
    """
    try:
        # Make API call to get archetype
        response = make_authenticated_request("GET", f"/api/datasets/{dataset_id}/archetype", profile)
        archetype_data = response.json()

        # Create output directory if it doesn't exist
        os.makedirs(out_dir, exist_ok=True)

        # Save the archetype to file
        output_file = os.path.join(out_dir, f"{dataset_id}.json")
        with open(output_file, 'w') as f:
            json.dump(archetype_data, f, indent=2)

        typer.secho(f"✅ Archetype downloaded to {output_file}", fg=typer.colors.GREEN)
        typer.echo(f"You can compile it using: epsilon compile {output_file}")

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

        output_path = compile_arch(archetype_file, out_file)
        typer.secho(f"✅ Model classes generated at {output_path}", fg=typer.colors.GREEN)

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
            typer.echo(f"  dataset.{first_key}")

            # If there's a nested structure, show that as an example too
            if isinstance(data[first_key], dict):
                nested_key = next(iter(data[first_key]))
                typer.echo(f"  dataset.{first_key}.{nested_key}")

    except Exception as e:
        typer.secho(f"Error: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)


if __name__ == "__main__":
    app()