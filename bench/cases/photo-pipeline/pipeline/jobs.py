import io

from PIL import Image

from pipeline.ops import OPS


def run_job(raw: bytes, steps: list) -> bytes:
    img = Image.open(io.BytesIO(raw))
    for step in steps:
        img = OPS[step["op"]](img, *step.get("args", []))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
