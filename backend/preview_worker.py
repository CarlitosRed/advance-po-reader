"""Bounded private source rendering in an expendable, time-limited subprocess."""
from io import BytesIO
import json
import sys

import pymupdf
from PIL import Image, ImageOps


def render(data, media, page, bbox):
    if media == "application/pdf":
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if not 1 <= page <= len(document) or document.is_encrypted:
                raise ValueError("invalid page")
            source = document[page - 1]
            scale = min(1400 / source.rect.width, 1800 / source.rect.height, 3)
            raster = source.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
        image = Image.open(BytesIO(raster)).convert("RGB")
    else:
        if page != 1:
            raise ValueError("invalid image page")
        with Image.open(BytesIO(data)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((1400, 1800))
    # Crop the visible raster, so normalized top-left references also work for
    # rotated PDF pages and EXIF-oriented photographs.
    if bbox:
        image = image.crop((int(bbox["x0"] * image.width), int(bbox["y0"] * image.height),
                           int(bbox["x1"] * image.width), int(bbox["y1"] * image.height)))
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


if __name__ == "__main__":
    try:
        sys.stdout.buffer.write(render(sys.stdin.buffer.read(20 * 1024 * 1024 + 1),
            sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])))
    except Exception:
        sys.exit(1)
