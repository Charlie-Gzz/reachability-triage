from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).parent / "static"


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_static("/static", STATIC)
    app.router.add_get("/", index)
    return app


async def index(request):
    return web.FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    web.run_app(create_app())
