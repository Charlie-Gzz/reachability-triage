from pathlib import Path

from aiohttp import web

SITE_ROOT = Path("/srv/sites")


def make_app() -> web.Application:
    app = web.Application()
    # Customer sites are symlinked in from the build cache.
    app.router.add_static("/sites", SITE_ROOT, follow_symlinks=True, show_index=False)
    app.router.add_get("/healthz", lambda r: web.Response(text="ok"))
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=8080)
