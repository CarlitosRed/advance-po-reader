"""Short-lived decoding worker. It emits metadata/error codes only."""
import io
import json
import sys
import warnings


def decode(data, max_pages, max_dimension, max_pixels):
    if data.startswith(b"%PDF-"):
        import pymupdf as fitz
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
        if b"%%EOF" not in data[-2048:]:
            return {"error": "malformed_pdf"}
        with fitz.open(stream=data, filetype="pdf") as document:
            if document.is_encrypted or document.needs_pass:
                return {"error": "encrypted_pdf"}
            count = document.page_count
            if not 1 <= count <= max_pages:
                return {"error": "pdf_page_limit"}
            if document.is_repaired:
                return {"error": "malformed_pdf"}
            for page in document:
                rect = page.rect
                if rect.width <= 0 or rect.height <= 0 or max(rect.width, rect.height) > 14400:
                    return {"error": "pdf_dimensions_invalid"}
                # Decode every page; scale output to a bounded pixel budget.
                scale = min(1.0, (2_000_000 / (rect.width * rect.height)) ** .5)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                if pixmap.width * pixmap.height > 2_100_000:
                    return {"error": "pdf_dimensions_invalid"}
            return {"media_type": "application/pdf", "page_count": count, "width": None, "height": None}
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = max_pixels
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG"}:
                return {"error": "unsupported_media_type"}
            if getattr(image, "n_frames", 1) != 1:
                return {"error": "animated_image_unsupported"}
            width, height = image.size
            if max(width, height) > max_dimension or width * height > max_pixels:
                return {"error": "image_dimension_limit"}
            media = "image/png" if image.format == "PNG" else "image/jpeg"
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
        return {"media_type": media, "page_count": 1, "width": width, "height": height}


if __name__ == "__main__":
    try:
        result = decode(sys.stdin.buffer.read(), *(int(v) for v in sys.argv[1:4]))
    except Exception:
        result = {"error": "file_decode_failed"}
    print(json.dumps(result))
    sys.exit(1 if "error" in result else 0)
