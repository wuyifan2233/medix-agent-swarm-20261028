from starlette.responses import JSONResponse


class ProfileBodyLimit:
    """Bound profile JSON before FastAPI parses it; unrelated routes are untouched."""
    def __init__(self, app, maximum=65536):
        self.app, self.maximum = app, maximum

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/profile') or scope.get('method') not in {'PUT','POST','DELETE'}:
            return await self.app(scope, receive, send)
        body = bytearray()
        maximum = 34*1024*1024 if scope.get('path')=='/api/profile/imports' else self.maximum
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if len(body) > maximum:
                return await JSONResponse({'detail':'请求超出大小限制。'}, status_code=413)(scope, receive, send)
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type':'http.request', 'body':bytes(body), 'more_body':False}
            return await receive()

        await self.app(scope, replay, send)
