from fastapi import FastAPI, Request

from gateway.middleware import AuthMiddleware

app = FastAPI()
app.add_middleware(AuthMiddleware)


@app.get("/me")
def me(request: Request):
    return request.state.claims
