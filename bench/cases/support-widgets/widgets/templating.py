from jinja2.sandbox import SandboxedEnvironment

# Support agents write their own reply macros, so templates are untrusted input.
_env = SandboxedEnvironment(autoescape=True)


def render_reply(source: str, ticket: dict) -> str:
    template = _env.from_string(source)
    return template.render(ticket=ticket, agent={"name": "Support"})


def render_reply_safe(source: str, ticket: dict) -> str:
    return _env.from_string(source).render(ticket=ticket)
