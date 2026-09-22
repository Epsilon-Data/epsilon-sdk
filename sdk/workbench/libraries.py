"""Notebook package metadata, separate from research code and observed outputs."""
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

LIBRARIES = {
    "numpy": ("numpy", "Numeric arrays"),
    "pandas": ("pandas", "Data tables"),
    "matplotlib": ("matplotlib", "Charts and figures"),
    "seaborn": ("seaborn", "Statistical charts and heatmaps"),
    "scipy": ("scipy", "Scientific computing"),
    "statsmodels": ("statsmodels", "Statistical models"),
    "ipython": ("IPython", "Rich notebook displays"),
}


def library_profile():
    requirements = Path(__file__).with_name("runtime").joinpath("requirements.txt").read_text()
    return [{"name": name, "module": LIBRARIES[name][0], "purpose": LIBRARIES[name][1], "requirement": line}
            for line in requirements.splitlines()
            if (match := re.match(r"^([a-zA-Z0-9_-]+)", line)) and (name := match.group(1).lower()) in LIBRARIES]


PROBE = """import importlib.metadata as metadata, json, platform
packages = {}
for name in %s:
    try:
        packages[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        pass
print(json.dumps({"python": platform.python_version(), "packages": packages}))
""" % repr(list(LIBRARIES))


@lru_cache(maxsize=8)
def installed_libraries(docker, image_id):
    """Inspect an immutable image once; no project mounts or user source."""
    from sdk.workbench.kernel import docker_environment
    result = subprocess.run([docker, "run", "--rm", "--pull=never", "--network=none", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65532:65532", "--memory=256m",
        "--pids-limit=32", "--cpus=1", "--log-driver=none", "--entrypoint=python", image_id, "-I", "-c", PROBE],
        capture_output=True, text=True, timeout=15, env=docker_environment())
    if result.returncode or len(result.stdout) > 20000:
        raise ValueError("Notebook library inventory is unavailable.")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError("Notebook library inventory is invalid.")
    versions, python = data.get("packages"), data.get("python")
    if not isinstance(versions, dict) or not isinstance(python, str) or not re.fullmatch(r"\d+\.\d+\.\d+", python):
        raise ValueError("Notebook library inventory is invalid.")
    packages = []
    for name, (module, purpose) in LIBRARIES.items():
        version = versions.get(name)
        if isinstance(version, str) and re.fullmatch(r"[a-zA-Z0-9.+_-]{1,80}", version):
            packages.append({"name": name, "module": module, "version": version, "purpose": purpose})
    return {"python": python, "packages": packages}


def model_libraries(status):
    """Only environment metadata enters model context; never kernel output."""
    return {"ready": status.get("available", False), "inventory_verified": status.get("inventory_verified", False),
            "python": status.get("python"),
            "packages": [{k: p[k] for k in ("name", "module", "version")} for p in status.get("packages", [])],
            "planned_packages": [p["name"] for p in library_profile()],
            "restart_for_update": status.get("update_available", False)}
