"""On-demand source-region rendering; no UI and no effect on extracted values.

Inspired by the tiling article's bounded work/caching idea, implemented against
the installed PDFium API. All callers sharing this process must use this lock.
"""
import hashlib
import io
import math
import threading
from collections import OrderedDict

import pypdfium2 as pdfium

PDFIUM_LOCK = threading.RLock()


class RegionRenderer:
    def __init__(self, budget_bytes=16 * 1024 * 1024, max_pixels=4_000_000):
        self.budget_bytes = budget_bytes
        self.max_pixels = max_pixels
        self._cache = OrderedDict()
        self._cost = 0

    def render(self, raw, page_number, bbox=None, scale=2):
        """Return PNG bytes for a top-left-origin PDF-coordinate region.

        bbox=(x0, top, x1, bottom); None requests a full page subject to limits.
        Cache identity includes document hash, page, bounds and resolution.
        """
        if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
            raise ValueError("Page numbers start at 1")
        if not isinstance(scale, (float,int)) or not math.isfinite(scale) or not 0.25 <= scale <= 6:
            raise ValueError("Choose a rendering scale from 0.25 to 6")
        key = (hashlib.sha256(raw).hexdigest(),page_number,tuple(bbox) if bbox is not None else None,scale)
        with PDFIUM_LOCK:
            if key in self._cache:
                value = self._cache.pop(key)
                self._cache[key] = value
                return value[0]
            with pdfium.PdfDocument(raw) as document:
                if page_number > len(document):
                    raise ValueError("Page not found")
                page = document[page_number-1]
                try:
                    width,height = page.get_size()
                    x0,top,x1,bottom = bbox or (0,0,width,height)
                    if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in (x0,top,x1,bottom)):
                        raise ValueError("Invalid rendering bounds")
                    if not (0<=x0<x1<=width and 0<=top<bottom<=height):
                        raise ValueError("Rendering bounds must stay within the page")
                    cost = math.ceil((x1-x0)*scale)*math.ceil((bottom-top)*scale)*4
                    if cost > self.max_pixels*4:
                        raise ValueError("This region is too large at that resolution; render a smaller region")
                    # PDFium uses crop amounts in left/bottom/right/top order.
                    bitmap = page.render(scale=scale,crop=(x0,height-bottom,width-x1,top),limit_image_cache=True)
                    try:
                        stream = io.BytesIO()
                        image = bitmap.to_pil()
                        try:
                            image.save(stream,format="PNG")
                        finally:
                            image.close()
                        png = stream.getvalue()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            if cost <= self.budget_bytes:
                while self._cache and self._cost+cost > self.budget_bytes:
                    _,(_,old_cost) = self._cache.popitem(last=False)
                    self._cost -= old_cost
                self._cache[key] = (png,cost)
                self._cost += cost
            return png

    def clear(self):
        with PDFIUM_LOCK:
            self._cache.clear()
            self._cost = 0
