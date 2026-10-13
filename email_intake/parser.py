"""Bounded MIME metadata extraction. Archives and documents are opaque bytes."""
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from hashlib import sha256
from html.parser import HTMLParser
import re

MAX_EMAIL = 2 * 1024 * 1024
MAX_HEADERS = 32 * 1024
MAX_DEPTH = 8
MAX_PARTS = 64
MAX_ATTACHMENTS = 24
MAX_BODY = 12_000
SUPPORTED = {"application/pdf": (".pdf", b"%PDF-"),
             "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
             "image/jpeg": (".jpg", b"\xff\xd8\xff")}
SAFE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class ParseError(ValueError):
    pass


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "object", "template"}:
            self.blocked.append(tag)
        if not self.blocked and tag in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()
        if not self.blocked and tag in {"p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


@dataclass
class Parsed:
    sender: str
    subject: str
    message_id: str | None
    body: str
    body_segments: list
    attachments: list
    payloads: dict = field(repr=False)

    def record(self):
        return {"sender": self.sender, "subject": self.subject, "message_id": self.message_id,
                "body": self.body, "body_segments": self.body_segments,
                "attachment_manifest": self.attachments}


def preflight(raw):
    if len(raw) > MAX_EMAIL:
        raise ParseError("LIMIT")
    # Reject pathological nesting/headers BEFORE the recursive stdlib MIME parser.
    # Counting all boundary declarations is conservative, including quoted ones.
    if len(re.findall(br"boundary\s*=", raw, re.I)) > MAX_DEPTH:
        raise ParseError("LIMIT")
    first = re.split(br"\r?\n\r?\n", raw, maxsplit=1)
    if len(first) != 2 or len(first[0]) > MAX_HEADERS:
        raise ParseError("PARSE_FAILED")
    if len(re.findall(br"(?im)^content-type:", raw)) > MAX_PARTS:
        raise ParseError("LIMIT")


def parse(raw):
    preflight(raw)
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        if not msg.get("From") or not msg.get("Subject"):
            raise ParseError("PARSE_FAILED")
        for header in ("From", "Subject", "Message-ID", "Content-Type"):
            if len(msg.get_all(header, [])) > 1:
                raise ParseError("PARSE_FAILED")
        plain, html, attachments, payloads = [], [], [], {}
        stack, count = [(msg, 0)], 0
        while stack:
            part, depth = stack.pop()
            count += 1
            if depth > MAX_DEPTH or count > MAX_PARTS:
                raise ParseError("LIMIT")
            if part.defects or any(getattr(h, "defects", ()) for h in part.values()):
                raise ParseError("PARSE_FAILED")
            for header in ("Content-Type", "Content-Transfer-Encoding", "Content-Disposition"):
                if len(part.get_all(header, [])) > 1:
                    raise ParseError("PARSE_FAILED")
            if str(part.get("Content-Transfer-Encoding", "7bit")).lower() not in {
                    "7bit", "8bit", "binary", "base64", "quoted-printable"}:
                raise ParseError("PARSE_FAILED")
            media = part.get_content_type()
            if media.startswith("message/"):
                # An attached email is evidence, not a second top-level order.
                raise ParseError("PARSE_FAILED")
            if part.is_multipart():
                stack.extend((p, depth + 1) for p in reversed(part.get_payload()))
                continue
            data = part.get_payload(decode=True)
            if not isinstance(data, bytes) or part.defects:
                raise ParseError("PARSE_FAILED")
            name = part.get_filename()
            is_attachment = (part.get_content_disposition() in {"attachment", "inline"}
                             or name is not None or media not in {"text/plain", "text/html"})
            if is_attachment:
                if len(attachments) >= MAX_ATTACHMENTS:
                    raise ParseError("LIMIT")
                aid = f"a{len(attachments) + 1:03}"
                name = name or "unnamed"
                # Filenames remain untrusted metadata, NEVER storage paths.
                extension = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                supported = (media in SUPPORTED and data.startswith(SUPPORTED[media][1])
                             and extension in SAFE_EXTENSIONS)
                attachments.append({"attachment_id": aid, "filename": name,
                                    "media_type": media, "byte_length": len(data),
                                    "sha256": sha256(data).hexdigest(),
                                    "disposition": part.get_content_disposition() or "attachment",
                                    "supported": supported})
                payloads[aid] = data
            else:
                charset = part.get_content_charset()
                try:
                    text = data.decode(charset or "utf-8", errors="strict")
                except UnicodeDecodeError:
                    if charset is not None:
                        raise
                    # Only undeclared text gets this fallback. Undefined CP1252
                    # bytes still refuse; explicit charsets are never repaired.
                    text = data.decode("cp1252", errors="strict")
                if media == "text/html":
                    cleaner = TextHTML()
                    cleaner.feed(text)
                    cleaner.close()
                    html.append("".join(cleaner.parts))
                else:
                    plain.append(text)
        # Retain both alternatives: different HTML can contain additional evidence.
        body = "\n".join(plain + [h for h in html if h not in plain]).strip()
        if len(body.encode("utf-8")) > MAX_BODY:
            raise ParseError("LIMIT")
        segments = []
        for line in body.splitlines(keepends=True):
            kind = "quoted" if line.lstrip().startswith(">") else "newest"
            if segments and segments[-1]["kind"] == kind:
                segments[-1]["text"] += line
            else:
                segments.append({"kind": kind, "text": line})
        mid = str(msg["Message-ID"]).strip() if msg.get("Message-ID") else None
        if mid and not re.fullmatch(r"<[^\s<>@]+@[^\s<>@]+>", mid):
            raise ParseError("PARSE_FAILED")
        return Parsed(str(msg["From"]), str(msg["Subject"]), mid, body,
                      segments, attachments, payloads)
    except ParseError:
        raise
    except (ValueError, TypeError, LookupError, UnicodeError, RecursionError, IndexError):
        raise ParseError("PARSE_FAILED") from None
