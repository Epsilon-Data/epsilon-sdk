"""Local browser capabilities, filesystem scope and outbound context policy."""
import hmac
import re
import secrets
import time
from pathlib import Path
from threading import RLock
from urllib.parse import urlparse

from sdk.workbench.errors import PublicError

COOKIE = "epsilon_workspace"
SECRET_PATTERNS = re.compile(
    r"(?<![\w-])(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})(?![\w-])|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bauthorization\s*[:=]\s*[\"']?Bearer\s+\S{8,}|"
    r"\b(?:api[_ -]?key|password|access_token|refresh_token|id_token|authorization)\b\s*[:=]\s*"
    r"(?![\"']?(?:required|optional|placeholder|example|none|null)\b)\S{8,}",
    re.IGNORECASE)


class LocalSessions:
    def __init__(self):
        self.launch_token = secrets.token_urlsafe(32)
        self.launch_control = secrets.token_urlsafe(32)
        self.launch_expires = time.monotonic() + 600
        self.sessions = {}
        self.lock = RLock()

    def fresh_launch(self, control):
        with self.lock:
            if not hmac.compare_digest(self.launch_control, control):
                raise PublicError("Run epsilon start in your terminal to open this workspace.")
            self.launch_token = secrets.token_urlsafe(32)
            self.launch_expires = time.monotonic() + 600
            return self.launch_token

    def bootstrap(self, token):
        with self.lock:
            if (not self.launch_token or time.monotonic() > self.launch_expires or
                    not hmac.compare_digest(self.launch_token, token)):
                raise PublicError("The launch link has expired or was already used. Run epsilon start again for a fresh link.")
            self.launch_token = ""
            session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[session] = {"csrf": csrf, "created": time.monotonic()}
            return session, csrf

    def get(self, token, expired=False):
        with self.lock:
            value = self.sessions.get(token or "")
            if value:
                age = time.monotonic() - value["created"]
                if age < (604800 if expired else 86400):
                    return value
                if age >= 604800:
                    self.sessions.pop(token or "", None)
            return None

    def renew(self, token, csrf):
        with self.lock:
            session = self.get(token, expired=True)
            if not session or not hmac.compare_digest(session["csrf"], csrf):
                raise PublicError("Open a fresh launch link from epsilon start to reconnect this browser.")
            session["created"] = time.monotonic()
            return session


def safe_path(root, relative, must_exist=True):
    root = Path(root).resolve()
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(part in ("..", ".") for part in path.parts):
        raise PublicError("Only files inside the selected project are allowed.")
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise PublicError("Symbolic links are not allowed for workspace files.")
    target = current.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise PublicError("The file is outside the project.")
    if must_exist and not target.is_file():
        raise PublicError("The required project file is missing: " + str(relative))
    return target


def allowed_host(host):
    try:
        parsed = urlparse("http://" + host)
        return (parsed.hostname in ("127.0.0.1", "localhost", "::1") and
                not parsed.username and not parsed.password and parsed.path in ("", "/"))
    except ValueError:
        return False


def safe_metadata(profile):
    """No observed values, ranges, counts, rare categories or arbitrary prose."""
    fields = [{"path": leaf.path, "type": leaf.type,
               "access": leaf.access_level, "releasable_as": leaf.releasable_as}
              for leaf in profile.all_leaves()
              if len(leaf.path) <= 160 and all(p.isidentifier() and not p.startswith("__") for p in leaf.path.split("."))]
    return {"unit": profile.grain.label, "has_entity_key": profile.has_dedupe_key,
            "synthetic": True, "fields": fields,
            "policy": "Questions and schema only. No dataset rows or measured summaries are sent automatically."}


def check_outbound(text, known_secrets=()):
    if not isinstance(text, str) or len(text) > 200000:
        raise PublicError("The model context is too large.")
    if SECRET_PATTERNS.search(text) or any(secret and len(secret) >= 8 and secret in text for secret in known_secrets):
        raise PublicError("This message appears to contain a credential. Remove it before using the assistant.")
    return text
