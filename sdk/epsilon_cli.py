import typer
import json
import os
import urllib.request
import configparser
from pathlib import Path

app = typer.Typer(help="CLI for downloading JSON archetypes, handling authentication, and generating Python model classes.")

# ---------- Configuration for Credentials ----------
CONFIG_DIR = Path.home() / ".sdk_epsilon"
CONFIG_PATH = CONFIG_DIR / "credentials.ini"


def load_credentials(profile: str = "default") -> tuple[str, str]:
    """
    Load API key and secret key for the given profile from credentials file.
    """
    if not CONFIG_PATH.exists():
        typer.secho("🔒 No credentials found. Please run `login` first.", fg=typer.colors.RED)
        raise typer.Exit(1)
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if profile not in config:
        typer.secho(f"🔒 Profile '{profile}' not found. Available profiles: {', '.join(config.sections())}", fg=typer.colors.RED)
        raise typer.Exit(1)
    section = config[profile]
    return section.get("api_key", ""), section.get("secret_key", "")

@app.command()
def login(
    api_key: str = typer.Option(..., prompt=True, help="Your API key."),
    secret_key: str = typer.Option(..., prompt=True, hide_input=True, help="Your API secret key."),
    profile: str = typer.Option("default", help="Profile name to store credentials under.")
):
    """
    Store API credentials locally for future authenticated commands.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH)
    config[profile] = {"api_key": api_key, "secret_key": secret_key}
    with open(CONFIG_PATH, "w") as f:
        config.write(f)
    typer.secho(f"✅ Credentials stored under profile '{profile}'.", fg=typer.colors.GREEN)

@app.command()
def logout(
    profile: str = typer.Option("default", help="Profile name to remove credentials for.")
):
    """
    Remove stored API credentials for the given profile.
    """
    if not CONFIG_PATH.exists():
        typer.secho("🔒 No credentials file found.", fg=typer.colors.RED)
        raise typer.Exit(1)
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    if profile not in config:
        typer.secho(f"🔒 Profile '{profile}' not found.", fg=typer.colors.RED)
        raise typer.Exit(1)
    config.remove_section(profile)
    # If no profiles left, delete the file, else write updated config
    if not config.sections():
        CONFIG_PATH.unlink()
        typer.secho("✅ All credentials removed, credentials file deleted.", fg=typer.colors.GREEN)
    else:
        with open(CONFIG_PATH, "w") as f:
            config.write(f)
        typer.secho(f"✅ Profile '{profile}' removed.", fg=typer.colors.GREEN)

# ---------- JSON-to-Classes Generator ----------

def to_pascal_case(s: str) -> str:
    return ''.join(word.capitalize() for word in s.replace('-', '_').split('_'))


def generate_class_definitions(name: str, data: dict, classes: dict):
    """
    Recursively generate class definitions from JSON structure.

    Args:
        name: Name of the class or root key.
        data: A dict representing the JSON object for this class.
        classes: A dict mapping class names to their code strings.
    """
    class_name = to_pascal_case(name)
    fields = []
    for key, value in data.items():
        if isinstance(value, dict):
            nested_name = to_pascal_case(key)
            fields.append(f"    {key}: {nested_name}")
            generate_class_definitions(key, value, classes)
        else:
            py_type = type(value).__name__
            fields.append(f"    {key}: {py_type}")
    class_def = f"class {class_name}:\n"
    class_def += "\n".join(fields) if fields else "    pass"
    class_def += "\n"
    classes[class_name] = class_def

@app.command()
def download_archetype(
    url: str,
    out_dir: str = "archetypes",
    profile: str = typer.Option("default", help="Which credentials profile to use (if auth needed).")
):
    """
    Download a JSON archetype from the given URL into a local folder.

    Args:
        url: The HTTP URL of the JSON archetype.
        out_dir: Directory to save the downloaded file (default: archetypes).
    """
    # Attempt to load credentials (if your download requires auth headers)
    api_key, secret_key = load_credentials(profile)
    # Here you could add headers: {'Authorization': f'Bearer {api_key}:{secret_key}'}

    os.makedirs(out_dir, exist_ok=True)
    filename = os.path.join(out_dir, os.path.basename(url))
    typer.echo(f"Downloading archetype from {url} to {filename}...")
    try:
        urllib.request.urlretrieve(url, filename)
        typer.secho("✔ Download complete!", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"✖ Error downloading file: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

@app.command()
def compile_archetype(
    schema_path: str = typer.Argument(..., help="Path to the JSON archetype file."),
    out_file: str = typer.Argument("generated_models.py", help="Filename for the generated Python models.")
):
    """
    Read a JSON file and generate Python model classes.

    Args:
        schema_path: Path to the JSON archetype file.
        out_file: Filename for the generated Python models (default: generated_models.py).
    """
    if not os.path.isfile(schema_path):
        typer.secho(f"✖ Schema file not found: {schema_path}", fg=typer.colors.RED)
        raise typer.Exit(1)

    with open(schema_path, 'r') as f:
        data = json.load(f)

    classes = {}
    generate_class_definitions("Root", data, classes)

    with open(out_file, 'w') as f:
        f.write("from typing import Any, List, Dict\n\n")
        for class_def in classes.values():
            f.write(class_def + "\n")

    typer.secho(f"✅ Generated models saved to {out_file}", fg=typer.colors.GREEN)

if __name__ == "__main__":
    app()
