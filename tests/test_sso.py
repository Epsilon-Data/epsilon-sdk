"""Public native-client SSO, callback boundaries and credential refresh."""
import base64
import copy
import hashlib
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from sdk import config, credentials, sso
from sdk.client import APIClient
from sdk.errors import AuthenticationError

def destination(response):
    assert response.status_code == 200
    assert '/assets/auth-return.js' in response.text
    return html.unescape(re.search(r'data-destination="([^"]+)"', response.text).group(1))


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def oidc(workspace, monkeypatch, signing_key):
    w = workspace
    issuer = "https://identity.example/realms/epsilon"
    monkeypatch.setenv("EPSILON_SSO_ISSUER", issuer)
    monkeypatch.delenv("EPSILON_SSO_CLIENT_ID", raising=False)
    monkeypatch.delenv("EPSILON_SSO_AUDIENCE", raising=False)
    w.hub.base_url = config.BASE_URL
    document = {"issuer": issuer, "authorization_endpoint": issuer + "/auth",
                "token_endpoint": issuer + "/token", "jwks_uri": issuer + "/certs",
                "code_challenge_methods_supported": ["S256"], "response_types_supported": ["code"],
                "authorization_response_iss_parameter_supported": True}
    key = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key(), as_dict=True)
    key.update(kid="fixture-key", alg="RS256", use="sig")
    o = SimpleNamespace(w=w, issuer=issuer, document=document, key=key,
                        identity_changes={}, access_changes={}, calls=[], grants=[],
                        callback_cookie="epsilon_workspace_8787_signin", refresh_error=None)

    def encode(claims):
        return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "fixture-key"})

    def tokens(refresh=False):
        instant = int(time.time())
        claims = {"iss": issuer, "sub": "researcher-subject", "aud": "epsilon.api", "jti": "grant-" + str(len(o.grants)),
                  "iat": instant, "exp": instant + 300}
        access = encode(dict(claims, **o.access_changes))
        result = {"access_token": access, "expires_in": 300, "token_type": "Bearer",
                  "refresh_token": "fixture-refresh-rotated" if refresh else "fixture-refresh-original",
                  "refresh_expires_in": 1800}
        if not refresh:
            attempt = next(iter(w.app.state.browser_signin.attempts.values()))
            identity = dict(claims, aud="sdk-client", nonce=attempt.nonce, preferred_username="researcher@example.org")
            identity.update(o.identity_changes)
            result["id_token"] = encode(identity)
        return result

    def request(method, url, **kwargs):
        o.calls.append((method, url, kwargs))
        if url.endswith("/.well-known/openid-configuration"):
            return copy.deepcopy(document)
        if url == document["jwks_uri"]:
            return {"keys": [copy.deepcopy(o.key)]}
        if url == document["token_endpoint"]:
            o.grants.append(kwargs["data"])
            refreshing = kwargs["data"]["grant_type"] == "refresh_token"
            if refreshing and o.refresh_error:
                raise sso.SignInError(o.refresh_error)
            return tokens(refreshing)
        raise AssertionError("Unexpected identity request")

    monkeypatch.setattr(sso, "_json_request", request)

    def start(return_to="/projects"):
        response = w.browser.post("/api/auth/start", json={"return_to": return_to})
        assert response.status_code == 200, response.text
        params = {k: v[0] for k, v in parse_qs(urlsplit(response.json()["url"]).query).items()}
        o.params = params
        return response

    def callback(**changes):
        params = {"state": o.params["state"], "code": "one-use-code", "iss": issuer}
        params.update(changes)
        return w.browser.get(sso.CALLBACK_PATH + "?" + urlencode(params),
                             headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                             follow_redirects=False)

    o.start, o.callback, o.tokens = start, callback, tokens
    return o


def test_browser_code_flow_uses_pkce_and_verified_identity_without_passwords(oidc):
    o, w = oidc, oidc.w
    response = o.start(w.path.replace("/api", "") + "?layout=both")
    params = o.params
    attempt = w.app.state.browser_signin.attempts[params["state"]]
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] == base64.urlsafe_b64encode(hashlib.sha256(attempt.verifier.encode()).digest()).rstrip(b"=").decode()
    assert len(attempt.verifier) >= 43 and params["scope"] == "openid profile email"
    assert "code_verifier" not in response.text and "client_secret" not in response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/auth/callback" in cookie
    completed = o.callback()
    assert destination(completed) == w.path.replace("/api", "") + "?layout=both"
    assert "code=" not in completed.text and w.hub.access_token not in completed.text
    assert w.browser.get('/assets/auth-return.js').status_code == 200
    assert credentials.status(w.bench.credentials_path)["username"] == "researcher@example.org"
    assert w.bench.credentials_path.stat().st_mode & 0o777 == 0o600
    assert "fixture-refresh-original" in w.bench.credentials_path.read_text()
    assert "fixture-refresh-original" not in w.browser.get("/api/session").text
    assert o.grants[0]["code_verifier"] == attempt.verifier
    assert "client_secret" not in o.grants[0]
    assert not w.app.state.browser_signin.attempts
    w.hub.authenticate.assert_not_called()


def test_start_requires_unlocked_browser_and_csrf(oidc):
    w = oidc.w
    with TestClient(w.app, base_url="http://127.0.0.1:8787") as stranger:
        assert stranger.post("/api/auth/start", json={}).status_code == 401
    assert w.browser.post("/api/auth/start", json={}, headers={"x-epsilon-csrf": "wrong"}).status_code == 403
    assert not oidc.calls


def test_callback_allows_top_level_return_without_loosening_other_routes(oidc):
    o, w = oidc, oidc.w
    o.start()
    binding = w.browser.cookies.get(o.callback_cookie)
    query = urlencode({"state": o.params["state"], "code": "one-use", "iss": o.issuer})
    response = w.browser.get(sso.CALLBACK_PATH + "?" + query, follow_redirects=False,
                             headers={"Cookie": o.callback_cookie + "=" + binding,
                                      "Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
    assert destination(response) == "/projects"
    assert w.browser.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert w.browser.get(sso.CALLBACK_PATH, headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"}).status_code == 403
    assert w.browser.post(sso.CALLBACK_PATH, json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


@pytest.mark.parametrize("failure", ["state", "cookie", "expiry", "session", "issuer", "cancel", "duplicate"])
def test_invalid_callbacks_never_exchange_or_save_tokens(oidc, failure):
    o, w = oidc, oidc.w
    o.start()
    changes = {}
    if failure == "state":
        changes["state"] = "forged"
    elif failure == "cookie":
        w.browser.cookies.clear()
    elif failure == "expiry":
        w.app.state.browser_signin.attempts[o.params["state"]].created -= 601
    elif failure == "session":
        w.app.state.local_sessions.sessions.clear()
    elif failure == "issuer":
        changes["iss"] = "https://attacker.example"
    elif failure == "cancel":
        changes["error"] = "access_denied"
    if failure == "duplicate":
        response = w.browser.get(sso.CALLBACK_PATH + "?state=" + o.params["state"] + "&state=forged&code=x", follow_redirects=False)
    else:
        response = o.callback(**changes)
    assert destination(response).startswith("/signin?auth_error=")
    assert not o.grants and not w.bench.credentials_path.exists()


def test_code_callback_is_single_use_and_newer_attempt_wins(oidc):
    o, w = oidc, oidc.w
    o.start()
    old = o.params["state"]
    o.start()
    assert old not in w.app.state.browser_signin.attempts
    assert destination(o.callback()) == "/projects"
    assert "expired" in destination(o.callback())
    assert len(o.grants) == 1


@pytest.mark.parametrize("claim,value", [("nonce", "wrong"), ("iss", "https://attacker.example"),
                                         ("aud", "other-client"), ("sub", "other-user"),
                                         ("exp", 1), ("azp", "other-client"), ("at_hash", "wrong")])
def test_identity_claims_are_verified_before_saving(oidc, claim, value):
    o = oidc
    o.identity_changes[claim] = value
    o.start()
    assert destination(o.callback()) == "/signin?auth_error=failed"
    assert not o.w.bench.credentials_path.exists()


def test_signature_and_api_audience_are_verified(oidc):
    o = oidc
    o.start()
    o.key["n"] = jwt.algorithms.RSAAlgorithm.to_jwk(rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key(), as_dict=True)["n"]
    assert "failed" in destination(o.callback())
    assert not o.w.bench.credentials_path.exists()


def test_access_token_requires_epsilon_api_audience(oidc):
    oidc.access_changes["aud"] = "unrelated-api"
    oidc.start()
    assert "failed" in destination(oidc.callback())
    assert not oidc.w.bench.credentials_path.exists()


@pytest.mark.parametrize("endpoint", ["token_endpoint", "authorization_endpoint", "jwks_uri"])
def test_discovery_cannot_redirect_credentials_to_another_origin(oidc, endpoint):
    oidc.document[endpoint] = "https://attacker.example/collect"
    assert oidc.w.browser.post("/api/auth/start", json={}).status_code == 400
    assert not oidc.grants and not oidc.w.app.state.browser_signin.attempts


@pytest.mark.parametrize("destination", ["https://attacker.example", "//attacker.example", "/api/auth/logout", "/projects\r\nLocation:x", "/projects/../../settings"])
def test_return_destination_is_a_local_workspace_route(oidc, destination):
    oidc.start(destination)
    assert next(iter(oidc.w.app.state.browser_signin.attempts.values())).return_to == "/projects"


def expire_access(path):
    import configparser
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    parser["default"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with path.open("w") as stream:
        parser.write(stream)


def test_refresh_rotation_is_shared_with_cli_and_not_exposed_to_ui(oidc):
    o, w = oidc, oidc.w
    o.start()
    o.callback()
    expire_access(w.bench.credentials_path)
    client = APIClient.from_config(w.bench.credentials_path)
    assert client.is_authenticated()
    assert o.grants[-1]["grant_type"] == "refresh_token"
    assert o.grants[-1]["refresh_token"] == "fixture-refresh-original"
    assert "fixture-refresh-rotated" in w.bench.credentials_path.read_text()
    assert "fixture-refresh-rotated" in credentials.stored_secrets(w.bench.credentials_path)
    assert "fixture-refresh-rotated" not in w.browser.get("/api/session").text
    assert len(o.grants) == 2


def test_refresh_revocation_requires_new_signin_without_repeated_requests(oidc):
    o, w = oidc, oidc.w
    o.start()
    o.callback()
    expire_access(w.bench.credentials_path)
    o.refresh_error = "invalid_grant"
    assert not credentials.status(w.bench.credentials_path)["authenticated"]
    assert not credentials.status(w.bench.credentials_path)["authenticated"]
    assert len(o.grants) == 2 and not credentials.stored_secrets(w.bench.credentials_path)[1]


def test_concurrent_refresh_uses_the_rotated_token_once(oidc):
    o, w = oidc, oidc.w
    o.start()
    o.callback()
    expire_access(w.bench.credentials_path)
    clients = [APIClient.from_config(w.bench.credentials_path, refresh=False) for _ in range(4)]
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(lambda client: credentials.refresh_client(client, w.bench.credentials_path), clients))
    assert all(client.is_authenticated() for client in results)
    assert len({client.access_token for client in results}) == 1
    assert len(o.grants) == 2


def test_refresh_outage_is_bounded_and_does_not_erase_credentials(oidc):
    o, w = oidc, oidc.w
    o.start()
    o.callback()
    expire_access(w.bench.credentials_path)
    before = w.bench.credentials_path.read_bytes()
    o.refresh_error = "connection"
    for _ in range(4):
        assert not credentials.status(w.bench.credentials_path)["authenticated"]
    assert len(o.grants) == 2
    assert w.bench.credentials_path.read_bytes() == before


def test_changing_server_does_not_send_saved_tokens_to_the_new_destination(oidc, monkeypatch):
    o, w = oidc, oidc.w
    o.start()
    o.callback()
    expire_access(w.bench.credentials_path)
    monkeypatch.setattr(config, "BASE_URL", "https://different.example")
    with pytest.raises(AuthenticationError, match="another Epsilon server"):
        APIClient.from_config(w.bench.credentials_path)
    assert len(o.grants) == 1


def test_signout_during_token_exchange_cannot_resurrect_credentials(oidc, monkeypatch):
    o, w = oidc, oidc.w
    o.start()
    binding = w.browser.cookies.get(o.callback_cookie)
    entered, release = Event(), Event()
    original = sso._json_request
    def slow(method, url, **kwargs):
        result = original(method, url, **kwargs)
        if method == "POST":
            entered.set()
            assert release.wait(3)
        return result
    monkeypatch.setattr(sso, "_json_request", slow)
    manager = w.app.state.browser_signin
    parameters = {"state": o.params["state"], "code": "one-use", "iss": o.issuer}
    with ThreadPoolExecutor() as pool:
        callback = pool.submit(manager.complete, parameters, binding, "http://127.0.0.1:8787")
        assert entered.wait(2)
        assert w.browser.post("/api/auth/logout", json={}).status_code == 200
        release.set()
        with pytest.raises(sso.SignInError):
            callback.result(timeout=3)
    assert not w.bench.credentials_path.exists()


def test_identity_http_transport_is_bounded_and_does_not_follow_redirects(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = 302
    response.iter_content.return_value = [b'{"error":"redirected"}']
    request = Mock(return_value=response)
    monkeypatch.setattr(sso.requests, "request", request)
    # This test uses the real helper; the oidc fixture deliberately isn't used.
    with pytest.raises(sso.SignInError):
        sso._json_request("POST", "https://identity.example/token", data={"code": "fixture"})
    assert request.call_args.kwargs["allow_redirects"] is False
    assert request.call_args.kwargs["stream"] is True
    response.status_code = 200
    response.iter_content.return_value = [b"x" * 262145]
    with pytest.raises(sso.SignInError):
        sso._json_request("GET", "https://identity.example/certs")
