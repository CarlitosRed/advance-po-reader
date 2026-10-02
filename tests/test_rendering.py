import io
import unittest

from PIL import Image

from po_reader.catalog import ROOT
from po_reader.rendering import RegionRenderer


class RenderingTests(unittest.TestCase):
    def setUp(self):
        if not (ROOT / 'data/originals/PO-5624.pdf').is_file():
            self.skipTest('Private PDF fixtures unavailable')
        self.raw=(ROOT/"data/originals/PO-5624.pdf").read_bytes()

    def test_region_dimensions_and_document_key(self):
        renderer=RegionRenderer()
        png=renderer.render(self.raw,1,(20,280,570,360),scale=2)
        with Image.open(io.BytesIO(png)) as image:
            self.assertEqual(image.size,(1100,160))
        self.assertIs(renderer.render(self.raw,1,(20,280,570,360),scale=2),png)
        other=(ROOT/"data/originals/PO1298947.pdf").read_bytes()
        self.assertNotEqual(renderer.render(other,1,(20,280,570,360),scale=2),png)

    def test_bounds_limits_and_eviction(self):
        renderer=RegionRenderer(budget_bytes=20_000,max_pixels=100_000)
        renderer.render(self.raw,1,(20,100,100,180),scale=1)
        self.assertEqual(len(renderer._cache),0)
        renderer=RegionRenderer(budget_bytes=30_000,max_pixels=100_000)
        renderer.render(self.raw,1,(20,100,100,180),scale=1)
        renderer.render(self.raw,1,(20,200,100,280),scale=1)
        self.assertEqual(len(renderer._cache),1)
        self.assertLessEqual(renderer._cost,30_000)
        for bounds in ((-1,0,10,10),(0,0,1000,1000),(0,0,0,10)):
            with self.assertRaises(ValueError):renderer.render(self.raw,1,bounds)
        with self.assertRaises(ValueError):renderer.render(self.raw,2,(0,0,10,10))
        with self.assertRaises(ValueError):renderer.render(self.raw,1,scale=6)
        renderer.clear();self.assertEqual(renderer._cost,0)


if __name__ == "__main__": unittest.main()
