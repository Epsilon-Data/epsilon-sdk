"""Optional isolated notebook sessions, with no arbitrary host-code fallback."""
import hashlib
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from sdk.workbench.errors import PublicError
from sdk.workbench.analysis import input_fingerprint, remember_digest
from sdk.workbench.display import render_output, legacy_fields
from sdk.workbench.security import safe_path
from sdk.workbench.store import identifier
from sdk.workbench.libraries import installed_libraries, library_profile

IMAGE = "epsilon-notebook:local"
MAX_MESSAGE = 1200000


def docker_environment():
    # The Docker client may need its normal context/config to find the daemon.
    # None of these host environment variables are passed into the container.
    return {key: value for key, value in os.environ.items()
            if key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY", "SYSTEMROOT", "USERPROFILE")}


_runtime_lock = threading.Lock()
_runtime_cache = None
_runtime_probe = None


def runtime_status(*, wait=True, refresh=False):
    """Single-flight discovery; chat uses stale status while it refreshes."""
    global _runtime_probe
    with _runtime_lock:
        cached = _runtime_cache
        if cached and not refresh and time.monotonic() - cached[0] < 30:
            return dict(cached[1])
        if _runtime_probe is None:
            _runtime_probe = threading.Event()
            event = _runtime_probe

            def probe():
                global _runtime_cache, _runtime_probe
                try:
                    value = _probe_runtime()
                except Exception:
                    value = {"available": False, "reason": "Notebook runtime discovery failed. Check Docker and retry.", "packages": [], "inventory_verified": False}
                with _runtime_lock:
                    _runtime_cache = (time.monotonic(), value)
                    _runtime_probe = None
                    event.set()

            threading.Thread(target=probe, name="epsilon-runtime-status", daemon=True).start()
        event = _runtime_probe
    if wait:
        event.wait(timeout=20)
        with _runtime_lock:
            cached = _runtime_cache
    if cached:
        return dict(cached[1], checking=not event.is_set())
    return {"available": False, "checking": True, "reason": "Checking the notebook runtime. Retry shortly.",
            "library_profile": library_profile(), "packages": [], "inventory_verified": False}


def _probe_runtime():
    profile = library_profile()
    base = {"image": IMAGE, "library_profile": profile, "packages": [], "inventory_verified": False}
    docker = shutil.which("docker")
    if not docker:
        return dict(base, available=False, reason="Docker is not installed. Notebook editing and export still work.")
    try:
        env = docker_environment()
        endpoint = env.get("DOCKER_HOST") if not env.get("DOCKER_CONTEXT") else None
        if not endpoint:
            context = subprocess.run([docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
                                     capture_output=True, text=True, timeout=5, env=env)
            endpoint = context.stdout.strip() if context.returncode == 0 else ""
        if not endpoint.startswith(("unix://", "npipe://")):
            return dict(base, available=False, reason="Use a local Docker daemon over its Unix socket or Windows named pipe. Remote and TCP contexts are not accepted.")
        result = subprocess.run([docker, "image", "inspect", IMAGE, "--format", "{{.Id}}"],
                                capture_output=True, text=True, timeout=5, env=env)
        digest = result.stdout.strip()
        if result.returncode != 0 or not digest.startswith("sha256:"):
            return dict(base, available=False, reason="Start Docker and run epsilon notebook-build once to prepare the isolated runtime.")
        status = dict(base, available=True, image_id=digest)
        try:
            status.update(installed_libraries(docker, digest), inventory_verified=True)
            names = {p["name"] for p in status["packages"]}
            missing = [p["name"] for p in profile if p["name"] not in names]
            status.update(missing_packages=missing, needs_rebuild=bool(missing))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            status["inventory_reason"] = "Installed libraries could not be checked. Retry after checking Docker."
        return status
    except (OSError, subprocess.TimeoutExpired):
        return dict(base, available=False, reason="The Docker daemon is unavailable. Start it to run notebook cells.")


def container_command(docker, name, snapshot, image_id):
    # No host network, socket, credentials, writable project mount, extra
    # capability or published port. The input snapshot is read-only.
    return [docker, "run", "--rm", "--interactive", "--pull=never", "--name", name,
            "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user=65532:65532", "--pids-limit=128", "--memory=1g", "--memory-swap=1g", "--cpus=1",
            "--ulimit", "nofile=1024:1024", "--log-driver=none",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=268435456,mode=1777",
            "--mount", "type=bind,source=" + str(snapshot) + ",target=/workspace/generated,readonly",
            image_id]


class Kernel:
    def __init__(self, project_dir, scratch_dir):
        status = runtime_status(refresh=True)
        if not status["available"] or status.get("checking"):
            # A slow re-check reports the previous "available" status, which
            # carries no reason.
            raise PublicError(status.get("reason") or "Checking the notebook runtime. Retry shortly.")
        self.runtime = status
        self.image_id = status["image_id"]
        fingerprint = input_fingerprint(project_dir)
        self.snapshot = Path(tempfile.mkdtemp(prefix="kernel-", dir=str(scratch_dir)))
        self.name = "epsilon-kernel-" + identifier()
        self.lock = threading.Lock()
        self.replies = queue.Queue(maxsize=4)
        self.process = None
        try:
            digest = hashlib.sha256()
            for name in ("archetype.json", "data.csv", "models.py", "__init__.py"):
                path = safe_path(project_dir, "generated/" + name, must_exist=name in ("data.csv", "archetype.json"))
                if path.exists():
                    with path.open("rb") as source, (self.snapshot / name).open("wb") as target:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            target.write(chunk)
                            if name in ("archetype.json", "data.csv"):
                                digest.update(chunk)
                    if name == "archetype.json":
                        digest.update(b"\0")
                    os.chmod(str(self.snapshot / name), 0o444)
            if fingerprint != input_fingerprint(project_dir):
                raise PublicError("The project changed while preparing the notebook. Retry with stable input files.")
            self.input_digest = digest.hexdigest()
            remember_digest(fingerprint, self.input_digest)
            os.chmod(str(self.snapshot), 0o755)
            self.process = subprocess.Popen(container_command(shutil.which("docker"), self.name, self.snapshot, self.image_id),
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            env=docker_environment(), bufsize=0)
            threading.Thread(target=self._read, daemon=True).start()
            ready = self.replies.get(timeout=40)
            if not isinstance(ready, dict) or ready.get("ready") is not True:
                raise PublicError("The isolated notebook kernel did not start.")
        except Exception:
            self.close()
            raise PublicError("The isolated notebook kernel could not start. Check Docker and rebuild the runtime image if needed.")

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_MESSAGE + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                    break
                response = json.loads(line)
                self.replies.put(response, timeout=1)
        except (ValueError, OSError, queue.Full):
            pass
        finally:
            try:
                self.replies.put({"error": "Runtime disconnected"}, timeout=1)
            except queue.Full:
                pass

    def execute(self, source, cancel_event=None):
        if not self.lock.acquire(blocking=False):
            raise PublicError("The notebook kernel is busy.")
        try:
            request_id = identifier()
            self.process.stdin.write((json.dumps({"id": request_id, "code": source, "timeout": 30}) + "\n").encode())
            self.process.stdin.flush()
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if cancel_event and cancel_event.is_set():
                    self.close()
                    raise PublicError("Execution interrupted. The kernel was stopped; saved notebook source is preserved.")
                try:
                    result = self.replies.get(timeout=.2)
                except queue.Empty:
                    continue
                if not isinstance(result, dict) or result.get("id") != request_id:
                    raise PublicError("The kernel stopped unexpectedly. Restart it before continuing.")
                # Drop arbitrary MIME/JavaScript, external resources and HTML
                # attributes before output ever leaves the kernel boundary.
                display = render_output(result, source)
                if result.get("restart_required"):
                    self.close()
                return legacy_fields({"display": display, "error": bool(result.get("error")),
                        "reviewed": False, "input_digest": self.input_digest, "image_id": self.image_id,
                        "kernel_id": self.name, "execution_count": result.get("execution_count") if type(result.get("execution_count")) is int else None,
                        "truncated": display["truncated"], "restart_required": bool(result.get("restart_required"))})
            self.close()
            raise PublicError("Execution timed out. The isolated kernel was stopped.")
        except OSError:  # includes BrokenPipeError
            self.close()
            raise PublicError("The notebook kernel disconnected. Restart it to continue.")
        finally:
            self.lock.release()

    def close(self):
        docker = shutil.which("docker")
        if docker and getattr(self, "name", None):
            try:
                subprocess.run([docker, "rm", "--force", self.name], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=5, env=docker_environment())
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        if getattr(self, "snapshot", None):
            shutil.rmtree(str(self.snapshot), ignore_errors=True)


class Kernels:
    def __init__(self, state_dir):
        self.scratch = Path(state_dir) / "kernels"
        self.scratch.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.items = {}
        self.starting = {}
        self.closed = False
        self.lock = threading.RLock()

    def status(self, project_id, notebook_id):
        current = runtime_status(wait=False)
        with self.lock:
            kernel = self.items.get((project_id, notebook_id))
            if kernel and kernel.process.poll() is None:
                return dict(kernel.runtime, active=True, update_available=bool(current.get("image_id") and current["image_id"] != kernel.image_id))
            starting = (project_id, notebook_id) in self.starting
        return dict(current, active=False, starting=starting)

    def get(self, project_id, notebook_id, project_dir):
        key = (project_id, notebook_id)
        with self.lock:
            if self.closed:
                raise PublicError("The workspace is stopping. Start it again before running cells.")
            if key in self.starting:
                raise PublicError("This notebook is starting. Wait for its current run to finish.")
            kernel = self.items.get(key)
            if kernel and kernel.process.poll() is None:
                return kernel
            if len(set(self.items) | set(self.starting)) >= 3 and key not in self.items:
                raise PublicError("Three notebook sessions are already open. Stop one before starting another.")
            self.items.pop(key, None)
            reservation = threading.Event()
            self.starting[key] = reservation
        # Docker may take tens of seconds. No registry/status lock is held.
        try:
            if kernel:
                kernel.close()
            kernel = Kernel(project_dir, self.scratch)
            with self.lock:
                if not reservation.is_set() and not self.closed:
                    self.items[key] = kernel
                    return kernel
            kernel.close()
            raise PublicError("Notebook startup was stopped. Run a cell to start again.")
        finally:
            with self.lock:
                if self.starting.get(key) is reservation:
                    self.starting.pop(key)

    def stop(self, project_id, notebook_id):
        with self.lock:
            kernel = self.items.pop((project_id, notebook_id), None)
            reservation = self.starting.get((project_id, notebook_id))
            if reservation:
                reservation.set()
        if kernel:
            kernel.close()

    def close(self):
        with self.lock:
            self.closed = True
            keys = set(self.items) | set(self.starting)
        for project_id, notebook_id in keys:
            self.stop(project_id, notebook_id)
