"""Let a service live under a path prefix behind nginx (e.g. /api/chat/docs on :5173)."""


class ForwardedPrefixMiddleware:
    """nginx strips the prefix and sends it as X-Forwarded-Prefix; using it as the ASGI
    root_path makes Swagger UI (/docs) load /api/chat/openapi.json instead of /openapi.json."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            prefix = dict(scope["headers"]).get(b"x-forwarded-prefix")
            if prefix:
                scope = {**scope, "root_path": prefix.decode()}
        await self.app(scope, receive, send)
