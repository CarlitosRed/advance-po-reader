"""Layout profiles for the seven inspected sample formats.

Coordinates are fractions of a 595 x 842 reference page. They are guarded by
document and table anchors. A new layout requires review, not guessed fields.
"""
def box(x0, y0, x1, y1):
    return (x0 / 595, y0 / 842, x1 / 595, y1 / 842)


PROFILES = [
    dict(id="dulux", anchors=["duluxdecoratorcentre", "supplierreference", "deliverto"],
         company=box(135, 778, 478, 790), shipping=box(365, 218, 566, 260),
         phone=box(404, 290, 480, 304), order=box(490, 85, 570, 104),
         table=box(20, 383, 570, 440), columns=dict(customer=(20, 80), description=(87, 300), vendor=(305, 400), quantity=(445, 490)),
         start="customer", header=box(20, 354, 570, 382), header_anchors=["description", "qty", "reference"]),
    dict(id="jones", anchors=["jonesandclark", "partno", "deliverto"],
         company=box(70, 131, 230, 145), shipping=box(70, 131, 230, 206), phone=None,
         order=box(395, 178, 455, 193), table=box(30, 333, 560, 400),
         columns=dict(customer=(30, 100), description=(180, 410), quantity=(102, 140), uom=(141, 175)),
         start="customer", header=box(30, 310, 560, 330), header_anchors=["partno", "quantity", "description"]),
    dict(id="huws", anchors=["huwsgray", "productdescription", "invoiceto"],
         company=box(345, 162, 545, 179), shipping=box(345, 162, 545, 240), phone=box(345, 222, 480, 240),
         order=box(280, 120, 365, 138), table=box(82, 445, 540, 600),
         columns=dict(description=(110, 430), quantity=(80, 105), uom=(493, 540)),
         start="quantity", header=box(45, 390, 540, 411), header_anchors=["quantity", "productdescription", "uom"]),
    dict(id="ptf", anchors=["ptfsupplies", "itemcode", "deliverto"],
         company=box(20, 92, 130, 109), shipping=box(230, 183, 365, 260), phone=box(134, 127, 195, 137),
         order=box(540, 162, 573, 175), table=box(20, 301, 570, 360),
         columns=dict(vendor=(20, 90), description=(97, 285), quantity=(290, 350)),
         start="vendor", header=box(20, 280, 570, 298), header_anchors=["itemcode", "description", "quantity"]),
    dict(id="ladders", anchors=["laddersandaccess", "deliveryaddress", "purchaseorderid"],
         company=box(0, 145, 150, 157), shipping=box(480, 144, 595, 191), phone=box(505, 197, 595, 210),
         order=box(77, 220, 145, 234), table=box(0, 343, 595, 390),
         columns=dict(vendor=(0, 60), description=(63, 416), quantity=(427, 475)),
         start="vendor", header=box(0, 310, 595, 335), header_anchors=["product", "code", "quantity"]),
    dict(id="caulfield", anchors=["caulfieldindustrial", "stocknumber", "unitof"],
         company=box(35, 52, 155, 66), shipping=box(337, 175, 465, 247), phone=box(337, 248, 415, 261),
         order=box(470, 73, 520, 86), table=box(25, 482, 580, 769), next_table=box(25, 198, 580, 480),
         columns=dict(vendor=(25, 105), description=(115, 312), quantity=(313, 355), uom=(361, 400)),
         start="vendor", header=box(25, 354, 580, 380), next_header=box(25, 164, 580, 191), header_anchors=["stocknumber", "description", "quantity"]),
    dict(id="selco", anchors=["selco", "mpn", "buyfromvendor"],
         company=box(50, 473, 151, 486), shipping=box(438, 156, 572, 217), phone=box(506, 304, 570, 317),
         order=box(166, 294, 272, 306), table=box(45, 380, 565, 406),
         columns=dict(customer=(45, 105), vendor=(108, 165), description=(166, 340), quantity=(345, 390), uom=(390, 445)),
         start="customer", header=box(45, 352, 565, 377), header_anchors=["mpn", "description", "quantity"]),
]
