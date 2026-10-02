"""Evidence coordinates follow the visible page, including rotation metadata."""
from io import BytesIO

from PIL import Image
import pymupdf

from backend.preview_worker import render

TOP_LEFT = {"x0":0,"y0":0,"x1":.5,"y1":.5}


def test_rotated_pdf_crop_points_to_visible_top_left():
    document=pymupdf.open()
    page=document.new_page(width=100,height=200)
    # Original lower-left is blue; a clockwise rotation puts it at visible TL.
    page.draw_rect(pymupdf.Rect(0,0,50,100),color=None,fill=(1,0,0))
    page.draw_rect(pymupdf.Rect(0,100,50,200),color=None,fill=(0,0,1))
    page.set_rotation(90)
    data=document.tobytes();document.close()
    with Image.open(BytesIO(render(data,"application/pdf",1,TOP_LEFT))) as crop:
        assert crop.size==(300,150)
        assert crop.getpixel((150,75))==(0,0,255)


def test_exif_photo_crop_points_to_visible_top_left():
    image=Image.new("RGB",(100,200),"white")
    image.paste("red",(0,0,50,100));image.paste("blue",(0,100,50,200))
    exif=image.getexif();exif[274]=6
    output=BytesIO();image.save(output,format="JPEG",quality=100,exif=exif)
    with Image.open(BytesIO(render(output.getvalue(),"image/jpeg",1,TOP_LEFT))) as crop:
        assert crop.size==(100,50)
        red,green,blue=crop.getpixel((50,25))
        assert blue>240 and red<15 and green<15
