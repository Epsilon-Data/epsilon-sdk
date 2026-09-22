"""Epsilon browser sign-in for a public native client (authorization code + PKCE).

No client secret, embedded login form, browser token storage or trusted JWT decode.
The configured issuer is trusted configuration; callback parameters never select
the issuer, token endpoint, API destination or client ID.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from urllib.parse import urlencode, urlsplit

import requests

from sdk import config
from sdk.errors import AuthenticationError

CALLBACK_PATH = "/auth/callback"
FLOW_TTL = 600
ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")
MESSAGES = {
    "configuration": "Epsilon browser sign-in is not configured for this server. Check the SDK sign-in settings.",
    "connection": "Could not reach Epsilon sign-in. Check your connection and try again.",
    "expired": "This sign-in attempt has expired or was already used. Choose Sign in with Epsilon again.",
    "cancelled": "Sign-in was cancelled. You can try again or continue with local projects.",
    "failed": "Epsilon sign-in could not be verified. Please try again.",
    "invalid_grant": "Your Epsilon session has ended. Choose Sign in with Epsilon again.",
}


class SignInError(AuthenticationError):
    def __init__(self, kind="failed"):
        self.kind = kind if kind in MESSAGES else "failed"
        self.public_message = MESSAGES[self.kind]
        super().__init__(self.public_message)


def _url(value):
    if not isinstance(value, str) or len(value) > 1000 or re.search(r"[\s\\]", value):
        raise SignInError("configuration")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise SignInError("configuration") from None
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in ("http", "https")
            or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"))):
        raise SignInError("configuration")
    try:
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise SignInError("configuration") from None


@dataclass(frozen=True)
class Settings:
    server: str
    issuer: str
    client_id: str
    audience: str = "epsilon.api"


def settings(server):
    server = server.rstrip("/")
    _url(server)
    issuer = os.environ.get("EPSILON_SSO_ISSUER", "")
    if not issuer and server == "https://app.epsilon-data.org":
        issuer = server + "/keycloak/realms/epsilon"
    issuer = issuer.rstrip("/")
    _url(issuer)
    client_id = os.environ.get("EPSILON_SSO_CLIENT_ID", "sdk-client")
    audience = os.environ.get("EPSILON_SSO_AUDIENCE", "epsilon.api")
    if any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value) for value in (client_id, audience)):
        raise SignInError("configuration")
    return Settings(server, issuer, client_id, audience)


def _json_request(method, url, **kwargs):
    """Bound identity responses and never follow token-bearing HTTP redirects."""
    try:
        with requests.request(method, url, timeout=(4, 10), stream=True,
                              allow_redirects=False, **kwargs) as response:
            chunks, size = [], 0
            for chunk in response.iter_content(8192):
                size += len(chunk)
                if size > 262144:
                    raise SignInError()
                chunks.append(chunk)
            value = json.loads(b"".join(chunks))
            if not isinstance(value, dict):
                raise SignInError()
            if response.status_code != 200:
                raise SignInError("invalid_grant" if value.get("error") == "invalid_grant" else "failed")
            return value
    except (requests.RequestException, OSError):
        raise SignInError("connection") from None
    except (ValueError, TypeError):
        raise SignInError() from None


def discovery(selected):
    document = _json_request("GET", selected.issuer + "/.well-known/openid-configuration")
    if (document.get("issuer") != selected.issuer
            or "S256" not in document.get("code_challenge_methods_supported", [])
            or "code" not in document.get("response_types_supported", [])):
        raise SignInError("configuration")
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if _url(document.get(name)) != _url(selected.issuer):
            raise SignInError("configuration")
    return document


def _encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _claims(token, jwks, selected, audience):
    # PyJWT and cryptography are installed with the workbench extra.
    try:
        import jwt
        if not isinstance(token, str) or not 1 <= len(token) <= 50000:
            raise SignInError()
        header = jwt.get_unverified_header(token)  # Key selection only.
        alg = header.get("alg")
        if alg not in ALGORITHMS or not isinstance(header.get("kid"), str):
            raise SignInError()
        candidates = [key for key in jwks.get("keys", [])
                      if key.get("kid") == header["kid"] and key.get("use", "sig") == "sig"
                      and key.get("alg", alg) == alg and "verify" in key.get("key_ops", ["verify"])]
        if len(candidates) != 1:
            raise SignInError()
        key = jwt.PyJWK.from_dict(candidates[0], algorithm=alg)
        claims = jwt.decode(token, key.key, algorithms=[alg], audience=audience,
                            issuer=selected.issuer, leeway=30,
                            options={"require": ["iss", "aud", "sub", "exp", "iat"]})
        if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 200:
            raise SignInError()
        return claims, alg
    except ImportError:
        raise SignInError("configuration") from None
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError):
        raise SignInError() from None


def verified_tokens(data, selected, document, nonce=None, subject=None):
    jwks = _json_request("GET", document["jwks_uri"])
    access, _ = _claims(data.get("access_token"), jwks, selected, selected.audience)
    if str(data.get("token_type", "")).lower() != "bearer" or (subject and access["sub"] != subject):
        raise SignInError()
    identity = None
    if nonce is not None or data.get("id_token"):
        identity, alg = _claims(data.get("id_token"), jwks, selected, selected.client_id)
        audiences = identity["aud"]
        if (identity["sub"] != access["sub"]
                or (identity.get("azp") and identity["azp"] != selected.client_id)
                or (isinstance(audiences, list) and len(audiences) > 1 and identity.get("azp") != selected.client_id)
                or (nonce is not None and not hmac.compare_digest(str(identity.get("nonce", "")).encode(), nonce.encode()))):
            raise SignInError()
        if "at_hash" in identity:
            digest = hashlib.new("sha" + alg[-3:], data["access_token"].encode("ascii")).digest()
            if not hmac.compare_digest(str(identity["at_hash"]).encode(), _encoded(digest[:len(digest) // 2]).encode()):
                raise SignInError()
    try:
        expires = min(float(data["expires_in"]), float(access["exp"]) - time.time())
        if not 0 < expires <= 86400 * 7:
            raise SignInError()
        refresh = data.get("refresh_token", "")
        refresh_seconds = float(data.get("refresh_expires_in", 0))
        if not isinstance(refresh, str) or len(refresh) > 50000 or not 0 <= refresh_seconds <= 86400 * 366:
            raise SignInError()
    except (ValueError, TypeError, KeyError, OverflowError):
        raise SignInError() from None
    instant = datetime.now(timezone.utc)
    auth = {"auth_method": "browser", "issuer": selected.issuer, "client_id": selected.client_id,
            "audience": selected.audience, "subject": access["sub"], "server_url": selected.server}
    # No offline_access scope: refresh remains tied to the normal Keycloak SSO session.
    if refresh and refresh_seconds > 0:
        auth.update(refresh_token=refresh, refresh_expires_at=(instant + timedelta(seconds=refresh_seconds)).isoformat())
    return {"access_token": data["access_token"], "expires_at": instant + timedelta(seconds=expires),
            "identity": identity or {}, "auth": auth}


def refresh(auth, server):
    if not isinstance(auth.get("subject"), str) or not auth.get("subject") or not auth.get("refresh_token"):
        raise SignInError("invalid_grant")
    selected = settings(server)
    if any(auth.get(key) != getattr(selected, attr) for key, attr in
           (("issuer", "issuer"), ("client_id", "client_id"), ("audience", "audience"), ("server_url", "server"))):
        raise SignInError("configuration")
    document = discovery(selected)
    data = _json_request("POST", document["token_endpoint"], data={
        "grant_type": "refresh_token", "client_id": selected.client_id,
        "refresh_token": auth["refresh_token"],
    })
    return verified_tokens(data, selected, document, subject=auth["subject"])


def return_path(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\\]", value) or len(value) > 1000:
        return "/projects"
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "/projects"
    if (parsed.scheme or parsed.netloc or parsed.fragment
            or not re.fullmatch(r"/(?:projects(?:/[A-Za-z0-9_-]{1,80}){0,3}|settings)", parsed.path)):
        return "/projects"
    return value


@dataclass
class Attempt:
    selected: Settings
    document: dict
    state: str
    verifier: str
    nonce: str
    binding: str
    session: str
    redirect_uri: str
    return_to: str
    created: float
    client: object
    processing: bool = False


class BrowserSignIn:
    def __init__(self, credentials_path, client_factory, sessions):
        self.credentials_path = credentials_path
        self.client_factory = client_factory
        self.sessions = sessions
        self.attempts = {}
        self.lock = RLock()

    def start(self, session, origin, destination="/projects"):
        if not self.sessions.get(session) or _url(origin)[0:2] not in (("http", "127.0.0.1"), ("http", "localhost"), ("http", "::1")):
            raise SignInError("expired")
        client = self.client_factory()
        selected = settings(client.base_url)
        document = discovery(selected)
        binding = secrets.token_urlsafe(32)
        attempt = Attempt(selected, document, secrets.token_urlsafe(32), secrets.token_urlsafe(64),
                          secrets.token_urlsafe(32), hashlib.sha256(binding.encode()).hexdigest(), session,
                          origin + CALLBACK_PATH, return_path(destination), time.monotonic(), client)
        with self.lock:
            self.attempts = {state: value for state, value in self.attempts.items()
                             if value.session != session and time.monotonic() - value.created < FLOW_TTL}
            if len(self.attempts) >= 32:
                raise SignInError("expired")
            self.attempts[attempt.state] = attempt
        query = urlencode({"client_id": selected.client_id, "redirect_uri": attempt.redirect_uri,
                           "response_type": "code", "response_mode": "query", "scope": "openid profile email",
                           "state": attempt.state, "nonce": attempt.nonce,
                           "code_challenge": _encoded(hashlib.sha256(attempt.verifier.encode()).digest()),
                           "code_challenge_method": "S256"})
        return {"url": document["authorization_endpoint"] + "?" + query, "binding": binding}

    def cancel(self, session):
        with self.lock:
            self.attempts = {state: value for state, value in self.attempts.items() if value.session != session}

    def complete(self, parameters, binding, origin):
        from sdk import credentials
        state = parameters.get("state", "")
        with self.lock:
            attempt = self.attempts.get(state)
            if (not attempt or attempt.processing or time.monotonic() - attempt.created >= FLOW_TTL
                    or not self.sessions.get(attempt.session) or not isinstance(binding, str)
                    or not hmac.compare_digest(attempt.binding, hashlib.sha256(binding.encode()).hexdigest())
                    or attempt.redirect_uri != origin + CALLBACK_PATH):
                raise SignInError("expired")
            attempt.processing = True
        try:
            if parameters.get("error"):
                raise SignInError("cancelled" if parameters["error"] == "access_denied" else "failed")
            issuer = parameters.get("iss")
            if ((issuer and issuer != attempt.selected.issuer)
                    or (attempt.document.get("authorization_response_iss_parameter_supported") and not issuer)):
                raise SignInError()
            code = parameters.get("code", "")
            if not isinstance(code, str) or not 1 <= len(code) <= 4096:
                raise SignInError()
            data = _json_request("POST", attempt.document["token_endpoint"], data={
                "grant_type": "authorization_code", "code": code, "client_id": attempt.selected.client_id,
                "redirect_uri": attempt.redirect_uri, "code_verifier": attempt.verifier,
            })
            result = verified_tokens(data, attempt.selected, attempt.document, nonce=attempt.nonce)
            # Sign-out or a newer attempt during network I/O must win.
            with self.lock:
                if self.attempts.get(state) is not attempt or not self.sessions.get(attempt.session):
                    raise SignInError("expired")
                if settings(attempt.client.base_url) != attempt.selected or config.BASE_URL.rstrip("/") != attempt.selected.server:
                    raise SignInError("configuration")
                attempt.client.access_token = result["access_token"]
                attempt.client.token_expires_at = result["expires_at"]
                identity = result["identity"]
                username = identity.get("preferred_username") or identity.get("email") or identity.get("name") or "Researcher"
                if not isinstance(username, str) or len(username) > 200:
                    username = "Researcher"
                credentials.save_client(attempt.client, username, self.credentials_path, auth=result["auth"])
            return attempt.return_to
        finally:
            with self.lock:
                self.attempts.pop(state, None)
