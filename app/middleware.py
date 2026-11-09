"""Request correlation middleware."""
from uuid import uuid4


class RequestCorrelation:
    """Attach a bounded correlation ID without buffering the request body."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming_headers = [(key.lower(), value) for key, value in scope["headers"]]
        identifiers = dict(incoming_headers)
        incoming = identifiers.get(b"x-request-id") or identifiers.get(b"x-audit-id") or b""
        request_id = incoming if 0 < len(incoming) <= 128 and all(32 <= c < 127 for c in incoming) else uuid4().hex.encode()
        # ServerErrorMiddleware is outermost and sees the original scope on 500.
        # Share only the state mapping with that outer layer.
        scope["state"] = dict(scope.get("state") or {}, request_id=request_id.decode("ascii"))
        scope = dict(scope)
        scope["headers"] = [
            (key, value) for key, value in scope["headers"]
            if key.lower() not in (b"x-request-id", b"x-audit-id")
        ] + [(b"x-request-id", request_id), (b"x-audit-id", request_id)]
        if scope["app"].state.tracer is not None:
            from opentelemetry import trace
            trace.get_current_span().set_attribute("request.id", request_id.decode("ascii"))

        async def audited_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", request_id), (b"x-audit-id", request_id)
                ]
            await send(message)

        await self.app(scope, receive, audited_send)
