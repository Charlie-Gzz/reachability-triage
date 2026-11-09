from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(loader=FileSystemLoader("theme"), autoescape=select_autoescape(["html"]))


def render_page(page: dict, nav: list) -> str:
    template = env.get_template(page.get("layout", "page.html"))
    return template.render(page=page, nav=nav)


def build(pages: list, out_dir: str = "public") -> None:
    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    nav = [{"title": p["title"], "slug": p["slug"]} for p in pages]
    for page in pages:
        (out / f"{page['slug']}.html").write_text(render_page(page, nav))
