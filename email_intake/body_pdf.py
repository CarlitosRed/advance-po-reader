"""Small dependency-free, single-page derived text PDF; no lossy truncation."""
import textwrap


def render(text):
    # Built-in Courier/WinAnsi preserves Spanish and English without installing fonts.
    # Unsupported characters or text that will not fit require human source selection.
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise ValueError("PDF_LIMIT")
    text.encode("cp1252", errors="strict")
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n"):
        lines.extend(textwrap.wrap(line, 90, replace_whitespace=False,
                                   drop_whitespace=False) or [""])
    if len(lines) > 57:
        raise ValueError("PDF_LIMIT")
    commands = [b"BT /F1 9 Tf 12 TL 36 756 Td"]
    for line in lines:
        escaped = line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        commands.append(b"(" + escaped + b") Tj T*")
    commands.append(b"ET")
    stream = b"\n".join(commands)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(result)
    result.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(result)
