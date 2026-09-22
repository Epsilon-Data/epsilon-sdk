"""The default CLI server, independent of Chainlit and model providers."""
import socket
import threading
import webbrowser


def available():
    try:
        # Imported only to prove the workbench extras are installed;
        # ConfigDict exists only in pydantic 2.
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        from pydantic import ConfigDict  # noqa: F401
    except ImportError:
        return False
    return True


def serve(project_dir, port, open_browser=True, record=True):
    import uvicorn
    from sdk.workbench.api import build

    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    app = build(project_dir, record=record)
    remember_server(app, port)
    url = "http://127.0.0.1:{0}/#launch={1}".format(port, app.state.local_sessions.launch_token)
    if open_browser:
        timer = threading.Timer(1.2, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    return uvicorn.Server(config), url


def remember_server(app, port):
    """Publish a CLI-only capability in the researcher's private state folder."""
    import json
    import os
    import tempfile
    from pathlib import Path
    directory = Path(app.state.workbench.state_dir) / "servers"
    if directory.is_symlink():
        raise OSError("The server state directory must not be a symbolic link.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".server-", dir=str(directory))
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"pid": os.getpid(), "port": port, "control": app.state.local_sessions.launch_control}, stream)
        os.replace(temporary, directory / (str(port) + ".json"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def existing_launch_url(port, state_dir=None):
    """Refresh a link without restarting notebooks or trusting a bare localhost URL."""
    import json
    import os
    import stat
    import urllib.request
    from pathlib import Path
    root = Path(state_dir) if state_dir else Path.home() / ".epsilon_sdk"
    path = root / "servers" / (str(port) + ".json")
    try:
        if path.parent.is_symlink():
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
                return None
            value = json.loads(stream.read(4096))
        if value["port"] != port or not isinstance(value["control"], str):
            return None
        base = "http://127.0.0.1:{0}".format(port)
        request = urllib.request.Request(base + "/api/launch", data=json.dumps({"token": value["control"]}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=3) as response:
            token = json.load(response)["token"]
        if not isinstance(token, str) or not 20 <= len(token) <= 120 or not all(c.isalnum() or c in "_-" for c in token):
            return None
        return base + "/#launch=" + token
    except (OSError, KeyError, ValueError, TypeError):
        return None
