"""Create a synthetic, non-customer PO and source snippets for the UI prototype."""
from pathlib import Path
import json
import subprocess
import shutil

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "dist" / "assets"
SEED = ROOT.parent.parent / "data" / "catalog-seed.json"
POPLER = Path(shutil.which("pdftoppm") or "pdftoppm")
catalog = [{"id": p["id"], "name": p["name"]} for p in json.loads(SEED.read_text(encoding="utf-8"))["products"]]
(ASSETS / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")

rows = [
    ("7140618", "Werner MasterTrade 6 tread stepladder", "2", "EA"),
    ("7140818", "Werner MasterTrade 8 tread stepladder", "1", "EA"),
    ("7160618", "Werner fibreglass 6 tread stepladder", "3", "EA"),
    ("7050718L", "Werner 7 tread workstation - 7050718", "2", "EA"),
    ("79009", "Werner roof rack clamps", "1", "PK"),
    ("", "DELIVERY NOTE: call before arrival", "", ""),
    ("", "Carriage / shipping charge", "1", ""),
]
pdf_path = ASSETS / "sample-purchase-order.pdf"
c = canvas.Canvas(str(pdf_path), pagesize=A4)
c.setTitle("Sample Purchase Order - Interactive UI Prototype")
c.setAuthor("SmarterCommerce UI prototype")
width, height = A4
c.setFillColor(HexColor("#153a60"))
c.rect(0, height - 12, width, 12, fill=1, stroke=0)
c.setFont("Helvetica-Bold", 10)
c.drawString(40, height - 54, "SAMPLE DOCUMENT / NO CUSTOMER DATA")
c.setFont("Helvetica-Bold", 25)
c.drawString(40, height - 94, "PURCHASE ORDER")
c.setFont("Helvetica", 11)
c.drawString(40, height - 119, "PO number: DEMO-1042")
c.drawRightString(width - 40, height - 119, "Page 1 of 1")
c.setStrokeColor(HexColor("#dde4eb"))
c.line(40, height - 142, width - 40, height - 142)
c.setFont("Helvetica-Bold", 10)
c.drawString(40, height - 171, "BILL TO")
c.drawString(310, height - 171, "DELIVER TO")
c.setFont("Helvetica", 11)
c.drawString(40, height - 193, "Sample customer")
c.drawString(310, height - 193, "Sample customer warehouse")
c.setFillColor(HexColor("#576b7e"))
c.setFont("Helvetica", 10)
c.drawString(40, height - 214, "For workflow demonstration only")
c.drawString(310, height - 214, "No real delivery address included")

table_top = 280
c.setFillColor(HexColor("#edf2f7"))
c.rect(40, height - table_top - 30, width - 80, 30, fill=1, stroke=0)
c.setFillColor(HexColor("#182d42"))
c.setFont("Helvetica-Bold", 10)
for x, label in [(50, "PRODUCT NO."), (160, "DESCRIPTION"), (488, "QTY"), (531, "UNIT")]:
    c.drawString(x, height - table_top - 20, label)
regions = {}
for index, (sku, name, quantity, unit) in enumerate(rows, start=1):
    top = table_top + 30 + (index - 1) * 58
    if index % 2 == 0:
        c.setFillColor(HexColor("#f8fafc"))
        c.rect(40, height - top - 58, width - 80, 58, fill=1, stroke=0)
    c.setFillColor(HexColor("#182d42"))
    c.setFont("Helvetica", 10.5)
    c.drawString(50, height - top - 26, sku)
    c.drawString(160, height - top - 26, name)
    c.drawString(488, height - top - 26, quantity)
    c.drawString(531, height - top - 26, unit)
    c.setStrokeColor(HexColor("#dde4eb"))
    c.line(40, height - top - 58, width - 40, height - top - 58)
    regions[f"line-{index}"] = {"top": top / height * 100, "height": 58 / height * 100, "page": 1}
c.setFillColor(HexColor("#576b7e"))
c.setFont("Helvetica", 9)
c.drawString(40, 60, "Sample SKU and pack conflicts intentionally included for review.")
c.drawString(40, 43, "Product labels come from the provisional sample catalog, not a live store catalog.")
c.save()
subprocess.run([str(POPLER), "-png", "-r", "144", "-singlefile", str(pdf_path), str(ASSETS / "sample-page")], check=True)
page = Image.open(ASSETS / "sample-page.png")
scale = page.height / height
for index in range(1, 8):
    top = table_top + 30 + (index - 1) * 58
    page.crop((40 * scale, top * scale, (width - 40) * scale, (top + 58) * scale)).save(ASSETS / f"line-{index}.png")
(ASSETS / "regions.json").write_text(json.dumps(regions, indent=2), encoding="utf-8")
text = PdfReader(str(pdf_path)).pages[0].extract_text()
assert all(sku in text for sku in ["7140618", "7140818", "7050718L", "79009"])
assert "NO CUSTOMER DATA" in text
print(f"Created {pdf_path}")
print(f"Rendered {page.width}x{page.height}; 7 source snippets; 18 provisional catalog labels.")
