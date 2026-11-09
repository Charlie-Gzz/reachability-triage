import io

from PIL import Image

SIZES = {"sm": (128, 128), "md": (512, 512)}


def make_thumbnails(raw: bytes) -> dict:
    out = {}
    for name, size in SIZES.items():
        img = Image.open(io.BytesIO(raw))
        img.thumbnail(size)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        out[name] = buf.getvalue()
    return out
