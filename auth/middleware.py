from starlette.responses import JSONResponse


class AuthBodyLimit:
    """Bound credential payloads before JSON parsing, including chunked requests."""
    def __init__(self, app, maximum=16384):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        protected = scope.get("path", "").startswith(("/api/auth/", "/api/admin/"))
        if scope["type"] != "http" or not protected or scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.maximum:
                return await JSONResponse({"detail": "请求内容过大。"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
