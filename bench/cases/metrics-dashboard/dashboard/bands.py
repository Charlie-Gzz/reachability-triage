import base64
import io

from PIL import Image, ImageMath


def composite(raw: bytes, expression: str) -> str:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    r, g, b = img.split()
    result = ImageMath.eval(expression, a=r, b=g, c=b)
    out = io.BytesIO()
    result.convert("L").save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode()
