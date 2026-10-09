"""Offline mechanical Markdown checks. Python 3.12 standard library only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import unicodedata
from urllib.parse import unquote, urlsplit

REPOSITORY = "CarlitosRed/advance-po-reader"
SHA = re.compile(r"[0-9a-f]{40}")
BLOCKED = {"data", "output", "project-data", "poc-catalog", ".git", ".venv", "node_modules"}
KEYS = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,})\b|"
                  r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|"
                  r"(?i:\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[A-Za-z0-9_/-]{16,})")


class CannotVerify(Exception):
    """Only fixed, value-free codes may leave trust boundaries."""


def safe_path(value: str, parent: str = "", allow_root=False) -> str:
    """Decode once, canonicalize dot segments, reject Windows aliases and private paths."""
    if not isinstance(value, str):
        raise CannotVerify("unsafe_path")
    value = html.unescape(value)
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise CannotVerify("unsafe_path")
    value = unquote(value, errors="strict")
    if not value or value.startswith(("/", "\\")) or "%" in value:
        raise CannotVerify("unsafe_path")
    if any(unicodedata.category(c)[0] == "C" or
           (unicodedata.category(c)[0] == "Z" and c != " ") for c in value):
        raise CannotVerify("unsafe_path")
    parts = parent.split("/") if parent else []
    for part in value.split("/"):
        if part == ".":
            continue
        if part == "..":
            if not parts:
                raise CannotVerify("unsafe_path")
            parts.pop()
            continue
        stem = part.split(".")[0].casefold()
        if (not part or part[-1:] in {".", " "} or part[:1] == " " or
                any(c in part for c in '\\:*?"<>|~') or part.casefold().startswith(".env") or
                part.casefold() in BLOCKED or stem in {"con", "prn", "aux", "nul"} or
                re.fullmatch(r"(?:com|lpt)[1-9]", stem)):
            raise CannotVerify("unsafe_path")
        parts.append(part)
    if not parts:
        if allow_root:
            return "."
        raise CannotVerify("unsafe_path")
    return "/".join(parts)


def canonical(value: str) -> str:
    path = safe_path(value)
    if path != value:
        raise CannotVerify("unsafe_path")
    return path


def guarded_absolute(path: Path, allow_packages=False) -> Path:
    path = path.absolute()
    for part in path.parts[1:]:
        if not (allow_packages and part == "node_modules"):
            safe_path(part)
    for candidate in [*reversed(path.parents), path]:
        try:
            stat = candidate.lstat()
        except FileNotFoundError:
            continue
        if candidate.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise CannotVerify("unsafe_filesystem_alias")
    return path.resolve()


class Tree:
    def __init__(self, root: Path):
        self.root = guarded_absolute(root)
        self.cache = {}
        self.commits = {}
        self.checked_objects = set()
        self.blobs = {}
        if self.git("rev-parse", "--show-toplevel").strip().decode().replace("\\", "/").casefold() != self.root.as_posix().casefold():
            raise CannotVerify("repository_root_required")

    def git(self, *args: str, codes=(0,)) -> bytes:
        try:
            result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                    timeout=20, env={**os.environ, "GIT_NO_LAZY_FETCH": "1",
                                                    "GIT_TERMINAL_PROMPT": "0"})
        except (OSError, subprocess.TimeoutExpired):
            raise CannotVerify("git_unavailable") from None
        if result.returncode not in codes:
            raise CannotVerify("git_object_unavailable")
        return result.stdout

    def revision(self, revision: str) -> str:
        if revision in self.commits:
            return self.commits[revision]
        if not revision or revision.startswith("-") or any(c.isspace() for c in revision):
            raise CannotVerify("invalid_revision")
        sha = self.git("rev-parse", "--verify", revision).decode().strip()
        if not SHA.fullmatch(sha) or self.git("cat-file", "-t", sha).strip() != b"commit":
            raise CannotVerify("revision_not_commit")
        self.commits[revision] = sha
        self.commits[sha] = sha
        return sha

    def entries(self, sha: str) -> dict:
        if sha not in self.cache:
            self.revision(sha)
            entries = {}
            for row in self.git("ls-tree", "-r", "-t", "-z", sha).split(b"\0"):
                if row:
                    meta, name = row.split(b"\t", 1)
                    mode, kind, oid = meta.decode("ascii").split()
                    entries[name.decode("utf-8", errors="strict")] = (mode, kind, oid)
            self.cache[sha] = entries
        return self.cache[sha]

    def object(self, sha: str, path: str):
        if path == ".":
            self.revision(sha)
            oid = self.git("rev-parse", sha + "^{tree}").decode().strip()
            self.git("cat-file", "-e", oid)
            return ("040000", "tree", oid)
        canonical(path)
        entries = self.entries(sha)
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            row = entries.get("/".join(parts[:i]))
            if row and row[0] in {"120000", "160000"}:
                raise CannotVerify("unsafe_git_alias")
        row = entries.get(path)
        if row and row[2] not in self.checked_objects:
            self.git("cat-file", "-e", row[2])
            self.checked_objects.add(row[2])
        return row

    def local(self, path: str) -> Path:
        if path == ".":
            return self.root
        canonical(path)
        current = self.root
        for part in path.split("/"):
            current = current / part
            # Junctions, symlinks and all reparse points are refused before resolving.
            try:
                stat = current.lstat()
            except FileNotFoundError:
                continue
            if current.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise CannotVerify("unsafe_filesystem_alias")
        if not current.resolve().is_relative_to(self.root):
            raise CannotVerify("unsafe_path")
        return current

    def read(self, path: str, sha: str | None = None) -> bytes | None:
        if sha:
            row = self.object(sha, path)
            if row is None:
                return None
            if row[1] != "blob":
                raise CannotVerify("target_not_file")
            if row[2] not in self.blobs:
                self.blobs[row[2]] = self.git("cat-file", "blob", row[2])
            return self.blobs[row[2]]
        local = self.local(path)
        if not local.exists():
            return None
        if not local.is_file():
            raise CannotVerify("target_not_file")
        return local.read_bytes()

    def pages(self, selectors: list[str], sha: str | None) -> list[str]:
        found = set()
        for selector in selectors:
            selector = canonical(selector.rstrip("/"))
            if sha:
                entries = self.entries(sha)
                row = self.object(sha, selector)
                if row and row[1] == "blob" and selector.endswith(".md"):
                    matches = [selector]
                elif row and row[1] == "tree":
                    matches = [p for p in entries if p.startswith(selector + "/") and p.endswith(".md")]
                else:
                    matches = []
            else:
                local = self.local(selector)
                if local.is_file() and selector.endswith(".md"):
                    matches = [selector]
                elif local.is_dir():
                    matches = []
                    for directory, dirs, files in os.walk(local, followlinks=False):
                        # Do not enter private directories, even to list their contents.
                        allowed = []
                        for name in dirs:
                            rel = (Path(directory) / name).relative_to(self.root).as_posix()
                            try:
                                self.local(rel)
                                allowed.append(name)
                            except CannotVerify:
                                raise CannotVerify("selected_directory_unsafe") from None
                        dirs[:] = allowed
                        matches.extend((Path(directory) / n).relative_to(self.root).as_posix()
                                       for n in files if n.endswith(".md"))
                else:
                    matches = []
            if not matches:
                raise CannotVerify("selected_pages_missing")
            # Refuse selected aliases/private names before any document is read.
            for name in matches:
                canonical(name)
                if sha:
                    self.object(sha, name)
                else:
                    self.local(name)
            found.update(matches)
        if not found:
            raise CannotVerify("selected_pages_missing")
        return sorted(found)


@dataclass
class Link:
    label: str
    url: str
    line: int
    before: str = ""
    after: str = ""


def balanced(text: str, start: int, opening: str, closing: str):
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "\\":
            continue
        if i and text[i - 1] == "\\" and (i < 2 or text[i - 2] != "\\"):
            continue
        if text[i] == opening:
            depth += 1
        elif text[i] == closing:
            depth -= 1
            if depth == 0:
                return i
    return None


def destination(text: str):
    """Markdown destination and optional title, with escaped spaces/parentheses."""
    match = re.fullmatch(r'\s*(?:<([^<>\n]*)>|((?:\\.|[^\s])+?))(?:\s+(?:"[^"\n]*"|\'[^\'\n]*\'|\([^\n]*\)))?\s*', text)
    if not match:
        raise CannotVerify("markdown_destination_unverified")
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~ ])", r"\1", match[1] if match[1] is not None else match[2])


def parse_markdown(text: str):
    """Supported Markdown links, fences and headings. Unknown link syntax is not clean."""
    links, diagrams, errors = [], [], []
    lines = text.splitlines(keepends=True)
    masked = []
    fence = None
    block = []
    start_line = 0
    for line_number, line in enumerate(lines, 1):
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}\s*", line.rstrip("\r\n")):
                if fence[2] == "mermaid":
                    diagrams.append((start_line, "".join(block)))
                fence = None
            else:
                block.append(line)
            masked.append("\n" if line.endswith("\n") else "")
        elif opening:
            fence = (opening[1][0], len(opening[1]), opening[2].strip().casefold())
            start_line, block = line_number, []
            if "mermaid" in fence[2] and fence[2] != "mermaid":
                errors.append((line_number, "markdown_mermaid_info_unverified"))
            masked.append("\n" if line.endswith("\n") else "")
        else:
            if re.search(r"(?:`{3,}|~{3,})\s*mermaid\b", line, re.I):
                errors.append((line_number, "markdown_fence_context_unverified"))
            masked.append(line)
    if fence:
        errors.append((start_line, "markdown_unclosed_fence"))
    active = "".join(masked)
    heading_source = active
    # Code spans preserve offsets and newlines. Links inside them are examples.
    def mask_span(match):
        if active.rfind("[", 0, match.start()) > active.rfind("]", 0, match.start()):
            return match[0].replace("`", " ")
        return re.sub(r"[^\n]", " ", match[0])
    active = re.sub(r"(`+)([\s\S]*?)\1(?!`)", mask_span, active)
    active = re.sub(r"<!--[\s\S]*?-->", lambda m: re.sub(r"[^\n]", " ", m[0]), active)
    definitions = {}
    kept = []
    for line_number, line in enumerate(active.splitlines(keepends=True), 1):
        match = re.match(r"^ {0,3}\[([^\]]+)\]:\s*(.*)", line.rstrip("\r\n"))
        if match:
            name = " ".join(match[1].split()).casefold()
            try:
                url = destination(match[2])
                if name in definitions:
                    raise CannotVerify("markdown_duplicate_reference")
                definitions[name] = url
            except CannotVerify as exc:
                errors.append((line_number, str(exc)))
            kept.append("\n" if line.endswith("\n") else "")
        else:
            kept.append(line)
    active = "".join(kept)
    i = 0
    while i < len(active):
        char = active[i]
        if char == "\\":
            i += 2
            continue
        line_number = active.count("\n", 0, i) + 1
        if char == "[":
            end = balanced(active, i, "[", "]")
            if end is None:
                errors.append((line_number, "markdown_unclosed_label"))
                break
            label = active[i + 1:end]
            next_pos = end + 1
            url = None
            if next_pos < len(active) and active[next_pos] == "(":
                finish = balanced(active, next_pos, "(", ")")
                if finish is None:
                    errors.append((line_number, "markdown_unclosed_destination"))
                    break
                try:
                    url = destination(active[next_pos + 1:finish])
                except CannotVerify as exc:
                    errors.append((line_number, str(exc)))
                next_pos = finish + 1
            elif next_pos < len(active) and active[next_pos] == "[":
                finish = balanced(active, next_pos, "[", "]")
                if finish is None:
                    errors.append((line_number, "markdown_reference_unverified"))
                    break
                ref = active[next_pos + 1:finish] or label
                url = definitions.get(" ".join(ref.split()).casefold())
                if url is None:
                    errors.append((line_number, "markdown_reference_missing"))
                next_pos = finish + 1
            else:
                url = definitions.get(" ".join(label.split()).casefold())
            if url is not None:
                before = active[active.rfind("\n", 0, i) + 1:i]
                after = active[next_pos:active.find("\n", next_pos) if "\n" in active[next_pos:] else len(active)]
                links.append(Link(label, url, line_number, before, after))
            i = next_pos
        elif char == "<":
            finish = active.find(">", i + 1)
            if finish != -1 and re.match(r"(?:https?://|mailto:)", active[i + 1:finish]):
                url = active[i + 1:finish]
                links.append(Link("", url, line_number))
                i = finish + 1
            else:
                if re.match(r"</?(?:a|img)\b", active[i:], re.I):
                    errors.append((line_number, "html_link_unverified"))
                i += 1
        else:
            i += 1
    headings = set()
    counts = Counter()
    for line in heading_source.splitlines():
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?$", line)
        if match:
            title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", match[1])
            slug = re.sub(r"[^\w\- ]", "", html.unescape(title).casefold()).replace(" ", "-")
            count = counts[slug]
            counts[slug] += 1
            headings.add(slug + (f"-{count}" if count else ""))
    return links, diagrams, errors, headings


def visible_ranges(link: Link):
    label = link.label
    numeric = bool(re.fullmatch(r"\s*L?\d[\d\s,L\-–—to]*", label))
    numeric = numeric and bool(re.fullmatch(r"L\d+(?:-L\d+)?", unquote(urlsplit(link.url).fragment)))
    # Adjacent labels are admitted only at the immediate boundary, not across another link.
    if not re.search(r"\b(?:lines?\s+|L\d)", label, re.I) and not numeric:
        prior = re.search(r"\b(lines?\s+[\d\s,L\-–—to]+)\s*$", link.before, re.I)
        following = re.match(r"\s*[,:(]?\s*(lines?\s+[\d\s,L\-–—to]+)", link.after, re.I)
        if prior or following:
            label = (prior or following)[1]
        else:
            return None
    label = re.sub(r"^.*?\blines?\s+", "", label, flags=re.I)
    item = r"L?\d+(?:\s*(?:-|–|—|to)\s*L?\d+)?"
    match = re.fullmatch(r"\s*" + item + r"(?:\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)" + item + r")*\s*", label)
    if not match:
        raise CannotVerify("label_ambiguous")
    ranges = []
    for part in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", label):
        numbers = [int(n) for n in re.findall(r"\d+", part)]
        ranges.append((numbers[0], numbers[-1]))
    return ranges


def parse_mermaid(diagram: str, module: str | None) -> str:
    """Use installed Mermaid's parse API. Adapter prints a fixed protocol, no diagram."""
    if module:
        try:
            module = str(guarded_absolute(Path(module), allow_packages=True))
        except (CannotVerify, OSError, UnicodeError):
            return "unusable"
    node = shutil.which("node")
    if not node:
        return "unavailable"
    command = [node, str(Path(__file__).with_name("mermaid_adapter.mjs"))]
    if module:
        command.append(module)
    try:
        result = subprocess.run(command, input=diagram.encode(), capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "unusable"
    token = result.stdout.strip()
    if result.returncode == 0 and token == b"PASS":
        return "pass"
    if result.returncode == 1 and token == b"INVALID":
        return "invalid"
    if result.returncode == 2 and token == b"UNAVAILABLE":
        return "unavailable"
    return "unusable"


def strict_json(data: bytes):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs)


def load_hashes(root: Path, variable: str):
    name = os.environ.get(variable)
    if not name:
        return None
    raw_path = Path(name)
    if not raw_path.is_absolute():
        raise CannotVerify("private_hash_config")
    # Reject private names and reparse points before opening the external list.
    path = guarded_absolute(raw_path)
    if path.is_relative_to(root):
        raise CannotVerify("private_hash_config")
    try:
        config = strict_json(path.read_bytes())
        if (not isinstance(config, dict) or set(config) != {"version", "entries"} or
                type(config["version"]) is not int or config["version"] != 1 or
                not isinstance(config["entries"], list) or not config["entries"]):
            raise ValueError()
        entries = set()
        for row in config["entries"]:
            if (not isinstance(row, dict) or set(row) != {"words", "sha256"} or
                    type(row["words"]) is not int or not 1 <= row["words"] <= 32 or
                    not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ValueError()
            pair = (row["words"], row["sha256"])
            if pair in entries:
                raise ValueError()
            entries.add(pair)
        return entries
    except (OSError, ValueError, UnicodeError):
        raise CannotVerify("private_hash_config") from None


def newline_style(data: bytes):
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    styles = [name for name, count in (("CRLF", crlf), ("LF", lf), ("CR", cr)) if count]
    return "mixed" if len(styles) > 1 else (styles[0] if styles else "none")


@dataclass
class Report:
    findings: list = field(default_factory=list)
    unknowns: list = field(default_factory=list)
    pins: Counter = field(default_factory=Counter)
    targets: Counter = field(default_factory=Counter)
    target_lines: dict = field(default_factory=dict)
    links: int = 0
    outside: int = 0
    diagrams: int = 0
    diagram_passes: int = 0
    pages: int = 0
    hashes: str = "disabled"
    newest: str = "none"
    claims: str = "absent"
    base: str = "unverified"
    revision: str = "worktree"
    newline_compared: int = 0
    newline_added: int = 0

    def issue(self, code, page="-", line=0, detail="", unknown=False):
        (self.unknowns if unknown else self.findings).append((code, page, line, detail))

    @property
    def exit_code(self):
        return 2 if self.unknowns else (1 if self.findings else 0)

    def print(self):
        print("Offline documentation report")
        print(f"document_revision={self.revision} base={self.base}")
        print(f"pages={self.pages} links={self.links} outside_offline={self.outside} "
              f"mermaid={self.diagrams} mermaid_passed={self.diagram_passes}")
        print(f"private_hashes={self.hashes} pin_claims={self.claims} newest_pin={self.newest}")
        print(f"newline_compared={self.newline_compared} newline_added={self.newline_added}")
        print("Other remote URLs are outside offline verification.")
        print("| Page | SHA | Links |")
        print("| --- | --- | ---: |")
        for (page, sha), count in sorted(self.pins.items()):
            print(f"| {page} | {sha} | {count} |")
        for status, rows in (("FINDING", self.findings), ("UNVERIFIED", self.unknowns)):
            for code, page, line, detail in rows:
                print(f"{status} {page}:{line} {code}" + (f" {detail}" if detail else ""))
        print(f"findings={len(self.findings)} unverified={len(self.unknowns)} exit={self.exit_code}")


class Checker:
    def __init__(self, tree, report, args):
        self.tree, self.report, self.args = tree, report, args
        self.patterns = [re.compile(pattern, re.I) for pattern in ["project-data", "poc-catalog", *args.forbid]]
        self.hashes = load_hashes(tree.root, args.hash_env)
        report.hashes = "enabled" if self.hashes is not None else "disabled"
        self.revision = tree.revision(args.revision) if args.revision else None
        self.base = tree.revision(args.base) if args.base else None
        report.base = self.base or "disabled"
        report.revision = self.revision or "worktree"

    def check_privacy(self, page, text):
        count = sum(len(rx.findall(text)) for rx in self.patterns) + len(KEYS.findall(text))
        if count:
            self.report.issue("privacy", page, detail=f"count={count}")
        if self.hashes:
            # NFKC + casefold + whitespace collapse; punctuation stays significant.
            words = unicodedata.normalize("NFKC", text).casefold().split()
            matches = 0
            for width in {width for width, _ in self.hashes}:
                for offset in range(len(words) - width + 1):
                    value = " ".join(words[offset:offset + width])
                    if (width, hashlib.sha256(value.encode("utf-8")).hexdigest()) in self.hashes:
                        matches += 1
            if matches:
                self.report.issue("private_hash", page, detail=f"count={matches}")

    def check_anchor(self, page, link, fragment, target, sha):
        ranges = visible_ranges(link)
        if not fragment:
            if ranges:
                self.report.issue("label_without_anchor", page, link.line)
            return
        match = re.fullmatch(r"L(\d+)(?:-L(\d+))?", fragment)
        if match:
            if PurePosixPath(target).suffix.casefold() in {".pdf", ".docx", ".sqlite3", ".zip", ".png", ".jpg", ".jpeg", ".bin"}:
                raise CannotVerify("binary_line_anchor_unverified")
            data = self.tree.read(target, sha)
            if data is None:
                return
            first, last = int(match[1]), int(match[2] or match[1])
            if not 1 <= first <= last <= len(data.splitlines()):
                self.report.issue("anchor_bounds", page, link.line)
            if ranges is not None and ranges != [(first, last)]:
                self.report.issue("label_mismatch", page, link.line)
        elif fragment.startswith("L") and re.match(r"L\d", fragment):
            self.report.issue("anchor_malformed", page, link.line)
        elif target.endswith(".md"):
            data = self.tree.read(target, sha)
            if data is not None and fragment not in parse_markdown(data.decode("utf-8"))[3]:
                self.report.issue("heading_missing", page, link.line)
            if ranges:
                self.report.issue("label_without_line_anchor", page, link.line)
        else:
            self.report.issue("fragment_unverified", page, link.line, unknown=True)

    def check_link(self, page, link):
        url = html.unescape(link.url)
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            same = (parts.hostname or "").casefold() == "github.com" and parts.path.casefold().startswith("/" + REPOSITORY.casefold() + "/")
            if not same:
                if parts.scheme not in {"https", "http", "mailto"} or parts.netloc and not parts.scheme:
                    raise CannotVerify("unsafe_url")
                self.report.outside += 1
                return
            match = re.fullmatch("/" + re.escape(REPOSITORY) + r"/(blob|tree)/([^/]+)(?:/(.*))?", parts.path, re.I)
            if not match:
                if re.search(r"/(?:blob|tree)(?:/|$)", parts.path, re.I):
                    raise CannotVerify("git_url_unverified")
                self.report.outside += 1
                return
            kind, sha, raw = match.groups()
            if (not SHA.fullmatch(sha) or parts.scheme != "https" or parts.query or parts.username or parts.port):
                raise CannotVerify("git_url_unverified")
            if kind.casefold() == "tree" and not raw:
                target = "."
            elif not raw:
                raise CannotVerify("git_url_unverified")
            else:
                target = safe_path(raw[:-1] if kind.casefold() == "tree" and raw.endswith("/") else raw)
            self.tree.revision(sha)
            self.report.pins[page, sha] += 1
            self.report.targets[page, sha, target] += 1
            self.report.target_lines.setdefault((page, sha, target), link.line)
            row = self.tree.object(sha, target)
            if row is None:
                self.report.issue("link_missing", page, link.line)
                return
            expected = "blob" if kind.casefold() == "blob" else "tree"
            if row[1] != expected:
                self.report.issue("link_type", page, link.line)
                return
            if expected == "tree":
                if parts.fragment or visible_ranges(link):
                    self.report.issue("tree_anchor", page, link.line)
            else:
                self.check_anchor(page, link, unquote(parts.fragment), target, sha)
        else:
            if parts.query:
                raise CannotVerify("local_query_unverified")
            parent = str(PurePosixPath(page).parent)
            target = safe_path(parts.path.rstrip("/"), "" if parent == "." else parent, allow_root=True) if parts.path else page
            if self.revision:
                row = self.tree.object(self.revision, target)
                exists = row is not None
                is_file = bool(row and row[1] == "blob")
            else:
                local = self.tree.local(target)
                exists, is_file = local.exists(), local.is_file()
            if not exists:
                self.report.issue("link_missing", page, link.line)
            elif parts.fragment or visible_ranges(link):
                if not is_file:
                    self.report.issue("anchor_not_file", page, link.line)
                else:
                    self.check_anchor(page, link, unquote(parts.fragment), target, self.revision)

    def check_pins(self):
        pins = {sha for _, sha in self.report.pins}
        if not pins:
            return
        newest = []
        for sha in pins:
            if all(self._ancestor(old, sha) for old in pins):
                newest.append(sha)
        if len(newest) != 1:
            self.report.issue("pins_incomparable", unknown=True)
            return
        newest = newest[0]
        self.report.newest = newest
        for (page, sha, target), count in sorted(self.report.targets.items()):
            if sha == newest:
                continue
            old, new = self.tree.object(sha, target), self.tree.object(newest, target)
            if old is None or new is None:
                code = "pin_target_missing"
            elif old[1] != "blob" or new[1] != "blob":
                code = "pin_non_file"
            elif old[2] != new[2]:
                code = "pin_changed"
            else:
                continue
            self.report.issue(code, page, self.report.target_lines[page, sha, target], detail=f"links={count} older={sha}")

    def _ancestor(self, old, new):
        # A missing history is an unknown, not an incomparable-history assertion.
        return self.tree.git("merge-base", old, new, codes=(0, 1)).decode().strip() == old

    def check_claims(self, pages):
        raw = self.tree.read("docs/pin-claims.json", self.revision)
        if raw is None:
            return
        self.report.claims = "unverified"
        try:
            config = strict_json(raw)
            if (not isinstance(config, dict) or set(config) != {"version", "pages"} or
                    type(config["version"]) is not int or config["version"] != 1 or
                    not isinstance(config["pages"], dict)):
                raise ValueError()
            for page, rows in config["pages"].items():
                canonical(page)
                if page not in pages or not isinstance(rows, list):
                    raise ValueError()
                expected = Counter()
                for row in rows:
                    if (not isinstance(row, dict) or set(row) != {"target", "sha", "count"} or
                            not isinstance(row["sha"], str) or not SHA.fullmatch(row["sha"]) or
                            type(row["count"]) is not int or row["count"] < 1):
                        raise ValueError()
                    target = "." if row["target"] == "." else canonical(row["target"])
                    self.tree.revision(row["sha"])
                    key = (row["sha"], target)
                    if key in expected:
                        raise ValueError()
                    expected[key] = row["count"]
                actual = Counter({(sha, target): n for (p, sha, target), n in self.report.targets.items() if p == page})
                if actual != expected:
                    self.report.issue("claims_disagree", page)
            self.report.claims = "checked"
        except (ValueError, TypeError, UnicodeError, CannotVerify):
            raise CannotVerify("claims_malformed_or_unselected") from None

    def check_newlines(self, page, data):
        if not self.base:
            return
        previous = self.tree.read(page, self.base)
        if previous is None:
            self.report.newline_added += 1
            return
        self.report.newline_compared += 1
        if previous is not None and newline_style(previous) != newline_style(data):
            equal = previous.replace(b"\r\n", b"\n").replace(b"\r", b"\n") == data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            self.report.issue("newline_change", page, detail=f"{newline_style(previous)}->{newline_style(data)} content_equal={'yes' if equal else 'no'}")

    def check_diagram(self, page, line, diagram):
        self.report.diagrams += 1
        result = parse_mermaid(diagram, self.args.mermaid_module)
        if result == "pass":
            self.report.diagram_passes += 1
        else:
            self.report.issue("mermaid_" + result, page, line, unknown=result != "invalid")

    def run(self):
        pages = self.tree.pages(self.args.page or ["docs", "README.md"], self.revision)
        self.report.pages = len(pages)
        for page in pages:
            try:
                data = self.tree.read(page, self.revision)
                if data is None:
                    raise CannotVerify("selected_page_missing")
                text = data.decode("utf-8", errors="strict")
                self.check_privacy(page, text)
                self.check_newlines(page, data)
                links, diagrams, errors, _ = parse_markdown(text)
                for line, code in errors:
                    self.report.issue(code, page, line, unknown=True)
                for link in links:
                    self.report.links += 1
                    try:
                        self.check_link(page, link)
                    except (CannotVerify, ValueError, UnicodeError) as exc:
                        code = str(exc) if isinstance(exc, CannotVerify) else "link_unverified"
                        self.report.issue(code, page, link.line, unknown=True)
                for line, diagram in diagrams:
                    self.check_diagram(page, line, diagram)
            except (CannotVerify, OSError, UnicodeError) as exc:
                self.report.issue(str(exc) if isinstance(exc, CannotVerify) else "page_unreadable", page, unknown=True)
        for action in (self.check_pins, lambda: self.check_claims(pages)):
            try:
                action()
            except (CannotVerify, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
                self.report.issue(str(exc) if isinstance(exc, CannotVerify) else "check_unverified", unknown=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--revision", help="Read pages and local targets from this local Git commit")
    parser.add_argument("--base", default="HEAD", help="Compare selected page line endings with this local Git commit (default HEAD)")
    parser.add_argument("--page", action="append", help="Repository-relative Markdown file or directory; repeatable")
    parser.add_argument("--forbid", action="append", default=[], help="Additional case-insensitive privacy regex")
    parser.add_argument("--hash-env", default="DOCS_PRIVATE_HASHES", help="Variable containing external hash-only JSON path")
    parser.add_argument("--mermaid-module", help="Installed Mermaid module or entry point (no download)")
    args = parser.parse_args(argv)
    report = Report()
    try:
        Checker(Tree(args.repo), report, args).run()
    except (CannotVerify, OSError, UnicodeError, ValueError, re.error) as exc:
        report.issue(str(exc) if isinstance(exc, CannotVerify) else "configuration_unverified", unknown=True)
    report.print()
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
