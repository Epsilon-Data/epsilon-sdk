"""Same-origin local capability boundary using the public ASGI protocol."""
import hmac
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from sdk.workbench.security import COOKIE, allowed_host
from sdk.sso import CALLBACK_PATH

MAX_BODY = 2100000
WRITES = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
}


def cookie_name(request):
    return COOKIE + "_" + str(request.url.port or 80)


class LocalBoundary:
    def __init__(self, app, sessions):
        self.app, self.sessions = app, sessions

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)

        async def secured_send(message):
            if message["type"] == "http.response.start":
                message = dict(message, headers=list(message.get("headers", [])))
                message["headers"].extend((k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items())
            await send(message)

        async def reject(message, status, code=None):
            payload = {"error": message}
            if code:
                payload["code"] = code
            await JSONResponse(payload, status_code=status)(scope, receive, secured_send)

        host, origin = request.headers.get("host", ""), request.headers.get("origin")
        callback = scope["path"] == CALLBACK_PATH and request.method == "GET"
        # Only the sign-in callback admits a cross-site top-level GET. Its
        # one-use state, PKCE and separate browser cookie are checked by SSO.
        callback_navigation = callback and (
            not request.headers.get("sec-fetch-mode")
            or (request.headers.get("sec-fetch-mode") == "navigate"
                and request.headers.get("sec-fetch-dest") == "document"))
        if not allowed_host(host) or (origin and origin != "http://" + host and not callback_navigation):
            return await reject("This workspace accepts same-origin loopback requests only.", 403)
        if request.headers.get("sec-fetch-site") == "cross-site" and not callback_navigation:
            return await reject("Cross-site workspace access is blocked.", 403)
        writing = request.method in WRITES
        if writing:
            if not request.headers.get("content-type", "").lower().startswith("application/json"):
                return await reject("A JSON request is required.", 415)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return await reject("Invalid request length.", 400)
            if length < 0:
                return await reject("Invalid request length.", 400)
            if length > MAX_BODY:
                return await reject("Request too large.", 413)
        session = self.sessions.get(request.cookies.get(cookie_name(request)))
        scope.setdefault("state", {})["session"] = session
        path = scope["path"]
        public = path in ("/api/health", "/api/session", "/api/session/renew", "/api/bootstrap", "/api/launch")
        if path.startswith("/api/") and not public:
            if session is None:
                return await reject("Reconnect this browser using the launch link from epsilon start.", 401, "local_session_required")
            if writing and not hmac.compare_digest(session["csrf"], request.headers.get("x-epsilon-csrf", "")):
                return await reject("The local browser session is invalid. Reload the workspace.", 403)
        # Validate every project-scoped path segment before it can become an
        # identifier, SQL scope, filesystem name, or browser URL.
        if path.startswith("/api/projects/") and any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", part) for part in path.split("/")[3:]):
            return await reject("Invalid workspace identifier.", 422)
        if not writing:
            return await self.app(scope, receive, secured_send)
        chunks, length = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            length += len(chunk)
            if length > MAX_BODY:
                return await reject("Request too large.", 413)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body, delivered = b"".join(chunks), False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, secured_send)
