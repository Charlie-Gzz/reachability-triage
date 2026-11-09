from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from gateway.tokens import verify


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        header = request.headers.get("authorization", "")
        try:
            request.state.claims = verify(header.removeprefix("Bearer "))
        except Exception:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
