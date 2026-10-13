"""Conservative exact From matching. A sender hint is not authentication."""
from dataclasses import dataclass
from hashlib import sha256
import re

from .ledger import safe_path

MAX_LIST_BYTES = 64 * 1024
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
# Deliberately exclude plus tags, quoted local parts and non-ASCII identities.
LOCAL = re.compile(r"[a-z0-9!#$%&'/=^_{}|~-]+(?:\.[a-z0-9!#$%&'/=^_{}|~-]+)*")


class SenderListError(ValueError):
    pass


def domain(value):
    labels = value.split(".")
    return (value.isascii() and len(value) <= 253 and len(labels) >= 2
            and not all(label.isdigit() for label in labels)
            and all(LABEL.fullmatch(label) and not label.startswith("xn--") for label in labels))


def address(value):
    if not value.isascii() or len(value) > 254 or value.count("@") != 1:
        return False
    local, host = value.split("@")
    return len(local) <= 64 and bool(LOCAL.fullmatch(local)) and domain(host)


def from_address(header, raw_value):
    """Use the original parsed header, never display text or a decoded reparse."""
    if header.defects or len(header.addresses) != 1 or any(g.display_name is not None for g in header.groups):
        return None
    original = header.addresses[0].addr_spec
    if not original.isascii():
        return None
    value = original.lower()
    if not address(value):
        return None
    # Require the literal mailbox too: HeaderRegistry can normalize quoted local
    # parts or comments inserted inside an address into a trusted-looking value.
    # Accept a bare mailbox or one angle mailbox with a display name, followed
    # by simple comments. More elaborate syntax conservatively requires review.
    literal = re.escape(value)
    # Possessive runs cannot backtrack across overlapping whitespace/display
    # text. The unquoted display includes its trailing whitespace already.
    display = r'(?:"(?:[^"\\]|\\.)*+"\s*+|[^<>"]*+)'
    form = rf'\s*+(?:{literal}|{display}<\s*+{literal}\s*+>)\s*+(?:\([^()]*+\)\s*+)*+'
    return value if re.fullmatch(form, raw_value.lower()) else None


@dataclass(frozen=True)
class KnownSenders:
    addresses: frozenset
    domains: frozenset

    @property
    def fingerprint(self):
        canonical = "\n".join(sorted(self.addresses | self.domains))
        return sha256(("sender-hint-v1\n" + canonical).encode("ascii")).hexdigest()

    def matches(self, value):
        return (value is not None and address(value)
                and (value in self.addresses or value.rsplit("@", 1)[-1] in self.domains))


def load(path):
    """Read one bounded UTF-8 list; reject the whole file on any bad entry."""
    try:
        path = safe_path(path)
        # Check lexical and resolved components: Windows 8.3 names can hide
        # a .env-prefixed file or parent. Refuse junctions before resolving;
        # safe_path supplies symlink checks. These are pre-open checks, not
        # protection against concurrent path replacement or hard links.
        if any(part.lower().startswith(".env") or ":" in part for part in path.parts[1:]):
            raise SenderListError()
        if any(getattr(item, "is_junction", lambda: False)() for item in (path, *path.parents)):
            raise SenderListError()
        path = safe_path(path.resolve(strict=True))
        if any(part.lower().startswith(".env") or ":" in part for part in path.parts[1:]):
            raise SenderListError()
        with path.open("rb") as stream:
            data = stream.read(MAX_LIST_BYTES + 1)
        if len(data) > MAX_LIST_BYTES:
            raise SenderListError()
        text = data.decode("utf-8-sig")
        if not text.isascii() or any(ord(c) < 32 and c not in "\r\n\t" for c in text):
            raise SenderListError()
        entries = text.splitlines()
        addresses, domains = set(), set()
        for entry in entries:
            value = entry.strip().lower()
            if not value:
                continue
            if not entry.isascii() or any(ord(c) < 32 and c != "\t" for c in entry):
                raise SenderListError()
            if "@" in value and address(value):
                addresses.add(value)
            elif "@" not in value and domain(value):
                domains.add(value)
            else:
                raise SenderListError()
        if not addresses and not domains:
            raise SenderListError()
        return KnownSenders(frozenset(addresses), frozenset(domains))
    except (ValueError, OSError, UnicodeError):
        raise SenderListError() from None
