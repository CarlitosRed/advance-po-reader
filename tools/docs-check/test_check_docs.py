"""Fictional repositories only. Run with unittest discover; no third party tools."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import shutil
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_docs", HERE / "check_docs.py")
docs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = docs
spec.loader.exec_module(docs)


class CheckerTests(unittest.TestCase):
    def setUp(self):
        scratch = HERE.parents[1] / "tmp"
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch, prefix="docs-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.write("README.md", "# Fictional\n")
        self.write("docs/page.md", "# Page\n")
        self.write("src/file.py", "one\ntwo\nthree\n")
        self.old = self.commit()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-c", "core.hooksPath=" + str(self.root / "no-hooks"),
             "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "core.autocrlf=false", "-C", str(self.root), *args],
            stderr=subprocess.PIPE).decode().strip()

    def write(self, path, text):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(text.encode() if isinstance(text, str) else text)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "fictional")
        return self.git("rev-parse", "HEAD")

    def link(self, label="lines 1-2", sha=None, target="src/file.py", anchor="#L1-L2", kind="blob"):
        return f"[{label}](https://github.com/CarlitosRed/advance-po-reader/{kind}/{sha or self.old}/{target}{anchor})\n"

    def check(self, text=None, *args):
        if text is not None:
            if isinstance(text, str) and not text.endswith("\n"):
                text += "\n"
            self.write("docs/page.md", text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.dict(os.environ, {}, clear=False):
            code = docs.main(["--repo", str(self.root), "--page", "docs/page.md", *args])
        return code, out.getvalue()

    def test_link_pass(self):
        self.assertEqual(self.check("[source](../src/file.py)\n")[0], 0)

    def test_directory_trailing_slash_and_repository_root(self):
        self.assertEqual(self.check("[directory](../src/) [root](../)")[0], 0)
        self.assertEqual(self.check(self.link(label="tree", kind="tree", target="src/", anchor=""))[0], 0)
        self.assertEqual(self.check(self.link(label="tree", kind="tree", target="", anchor=""))[0], 0)

    def test_broken_link_bypass(self):
        code, out = self.check("[source](../src/absent.py)\n")
        self.assertEqual(code, 1)
        self.assertIn("link_missing", out)

    def test_all_link_forms_and_code_exclusion(self):
        text = ("[one](../src/file.py) ![two][id] [id][] [id]\n"
                "[id]: ../src/file.py \"title\"\n"
                f"<{self.link().split('](')[1].split(')')[0]}>\n"
                "`[ignored](missing)`\n~~~text\n[ignored](missing)\n~~~\n")
        code, out = self.check(text)
        self.assertEqual(code, 0, out)
        self.assertIn("links=5", out)

    def test_reference_missing_and_duplicate(self):
        for text in ("[x][missing]", "[x][r]\n[r]: ../src/file.py\n[r]: ../src/absent.py"):
            with self.subTest(text=text):
                self.assertEqual(self.check(text)[0], 2)

    def test_escaped_spaces_parentheses_and_nested_labels(self):
        self.write("src/a (b).py", "text\n")
        code, out = self.check(r"[a [nested]](../src/a\ \(b\).py)" + "\n[x](<../src/a%20%28b%29.py>)\n")
        self.assertEqual(code, 0, out)
        self.assertIn("links=2", out)

    def test_malformed_markdown_does_not_pass(self):
        for text in ("[x](../src/file.py", "[x](<../src/file.py)", "```mermaid\nflowchart TD\n"):
            with self.subTest(text=text):
                self.assertEqual(self.check(text)[0], 2)

    def test_external_links_are_explicit(self):
        code, out = self.check("[web](https://example.invalid/a) [mail](mailto:test@example.invalid)")
        self.assertEqual(code, 0)
        self.assertIn("outside_offline=2", out)

    def test_git_full_sha_pass(self):
        self.assertEqual(self.check(self.link())[0], 0)

    def test_git_missing_wrong_object_type_and_short_sha(self):
        blob = self.git("rev-parse", "HEAD:src/file.py")
        for sha in ("f" * 40, blob, self.old[:7], self.old + "\n"):
            with self.subTest(sha=sha):
                self.assertNotEqual(self.check(self.link(sha=sha))[0], 0)

    def test_git_blob_tree_route_types(self):
        self.assertEqual(self.check(self.link(label="source", target="src", anchor="", kind="tree"))[0], 0)
        for target, kind in (("src", "blob"), ("src/file.py", "tree")):
            with self.subTest(kind=kind):
                self.assertEqual(self.check(self.link(target=target, kind=kind, anchor=""))[0], 1)

    def test_git_missing_file(self):
        self.assertEqual(self.check(self.link(target="src/no.py"))[0], 1)

    def test_anchor_pass(self):
        self.assertEqual(self.check(self.link(label="file.py lines 1-3", anchor="#L1-L3"))[0], 0)

    def test_anchor_bounds_and_label_bypass(self):
        for label, anchor, expected in (("lines 1-4", "#L1-L4", "anchor_bounds"),
                                         ("lines 1-3", "#L1-L2", "label_mismatch"),
                                         ("line 0", "#L0", "anchor_bounds"),
                                         ("lines 3-1", "#L3-L1", "anchor_bounds")):
            with self.subTest(anchor=anchor):
                code, out = self.check(self.link(label=label, anchor=anchor))
                self.assertEqual(code, 1)
                self.assertIn(expected, out)

    def test_combined_ranges_not_silently_accepted(self):
        code, out = self.check(self.link(label="lines 1-2, 3", anchor="#L1-L2"))
        self.assertEqual(code, 1)
        self.assertIn("label_mismatch", out)
        self.assertEqual(self.check(self.link() + self.link(label="3", anchor="#L3"))[0], 0)

    def test_combined_and_ranges_and_code_labels(self):
        for label in ("lines 1-2 and 3", "lines 1, 2 and 3", "`lines 1-3`"):
            code, out = self.check(self.link(label=label))
            self.assertEqual(code, 1, out)
            self.assertIn("label_mismatch", out)

    def test_numeric_page_labels_are_not_line_labels(self):
        self.assertEqual(self.check("[01](../README.md)")[0], 0)

    def test_blank_code_only_link_label_is_not_ambiguous(self):
        self.assertEqual(self.check(self.link(label="`src/file.py`"))[0], 0)

    def test_adjacent_visible_label(self):
        code, out = self.check("lines 2-3 " + self.link(label="source"))
        self.assertEqual(code, 1)
        self.assertIn("label_mismatch", out)

    def test_missing_anchor_and_ambiguous_label(self):
        for label, anchor in (("lines 1-2", ""), ("lines 1 to 2 and following", "#L1-L2"),
                              ("source", "#L1-L2-L3")):
            with self.subTest(label=label):
                self.assertNotEqual(self.check(self.link(label=label, anchor=anchor))[0], 0)

    def test_local_heading_and_line_fragments(self):
        self.assertEqual(self.check("# Page\n[heading](#page) [lines 1-2](../src/file.py#L1-L2)")[0], 0)
        self.assertEqual(self.check("[heading](#missing)")[0], 1)

    def test_pin_same_blob_pass(self):
        self.write("src/other.py", "new\n")
        new = self.commit()
        code, out = self.check(self.link() + self.link(sha=new))
        self.assertEqual(code, 0, out)
        self.assertIn(self.old, out)
        self.assertIn(new, out)

    def test_pin_changed_blob_bypass(self):
        self.write("src/file.py", "changed\ntwo\nthree\n")
        new = self.commit()
        code, out = self.check(self.link() + self.link(sha=new))
        self.assertEqual(code, 1)
        self.assertIn("pin_changed", out)

    def test_pin_missing_target_at_newest(self):
        self.git("rm", "src/file.py")
        new = self.commit()
        code, out = self.check(self.link() + self.link(sha=new, target="README.md", label="source", anchor=""))
        self.assertEqual(code, 1)
        self.assertIn("pin_target_missing", out)

    def test_pin_non_file_target_at_newest(self):
        self.git("rm", "src/file.py")
        self.write("src/file.py/nested.py", "fictional\n")
        new = self.commit()
        code, out = self.check(self.link() + self.link(sha=new, target="README.md", label="source", anchor=""))
        self.assertEqual(code, 1)
        self.assertIn("pin_non_file", out)

    def test_pin_incomparable_histories(self):
        self.write("src/other.py", "branch a\n")
        left = self.commit()
        self.git("checkout", "-q", "--detach", self.old)
        self.write("src/other.py", "branch b\n")
        right = self.commit()
        code, out = self.check(self.link(sha=left) + self.link(sha=right))
        self.assertEqual(code, 2)
        self.assertIn("pins_incomparable", out)

    def claims(self, rows):
        self.write("docs/pin-claims.json", json.dumps({"version": 1, "pages": {"docs/page.md": rows}}))

    def test_claims_pass(self):
        self.claims([{"target": "src/file.py", "sha": self.old, "count": 1}])
        self.assertEqual(self.check(self.link())[0], 0)

    def test_claims_disagreement_bypass(self):
        self.claims([{"target": "src/file.py", "sha": self.old, "count": 2}])
        code, out = self.check(self.link())
        self.assertEqual(code, 1)
        self.assertIn("claims_disagree", out)

    def test_claims_field_matrix(self):
        valid = {"target": "src/file.py", "sha": self.old, "count": 1}
        for key, values in {"target": [None, "", "../src/file.py", ".env", "src/file.py "],
                            "sha": [None, "", self.old[:7], self.old + "\n"],
                            "count": [None, True, 1.0, "1", 0, -1]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    row = {**valid, key: value}
                    self.claims([row])
                    self.assertEqual(self.check(self.link())[0], 2)

    def test_claims_missing_duplicate_extra_and_wrong_pages(self):
        valid = {"target": "src/file.py", "sha": self.old, "count": 1}
        for value in ({}, {"version": True, "pages": {}}, {"version": 1, "pages": []},
                      {"version": 1, "pages": {"docs/unselected.md": []}},
                      {"version": 1, "pages": {"docs/page.md": [valid, valid]}},
                      {"version": 1, "pages": {}, "unknown": 1}):
            with self.subTest(value=value):
                self.write("docs/pin-claims.json", json.dumps(value))
                self.assertEqual(self.check(self.link())[0], 2)
        for text in ("{", '{"version":1,"version":1,"pages":{}}'):
            self.write("docs/pin-claims.json", text)
            self.assertEqual(self.check(self.link())[0], 2)

    def test_mermaid_pass_and_fail_with_injected_parser(self):
        with patch.object(docs, "parse_mermaid", return_value="pass"):
            self.assertEqual(self.check("```mermaid\nflowchart TD\nA-->B\n```\n")[0], 0)
        with patch.object(docs, "parse_mermaid", return_value="invalid"):
            code, out = self.check("```mermaid\nfictional secret diagram\n```\n")
            self.assertEqual(code, 1)
            self.assertNotIn("fictional secret", out)

    def test_mermaid_absent_and_broken_tool_are_unverified(self):
        for result in ("unavailable", "unusable"):
            with self.subTest(result=result), patch.object(docs, "parse_mermaid", return_value=result):
                code, out = self.check("```mermaid\nflowchart TD\nA-->B\n```\n")
                self.assertEqual(code, 2)
                self.assertIn("mermaid_" + result, out)

    def test_nested_and_extended_mermaid_fences_not_silently_skipped(self):
        for text in ("> ```mermaid\n> flowchart TD\n> ```\n", "```mermaid extra\nflowchart TD\n```\n"):
            with self.subTest(text=text):
                self.assertEqual(self.check(text)[0], 2)

    def test_actual_parser_adapter_missing_module(self):
        expected = "unusable" if shutil.which("node") else "unavailable"
        self.assertEqual(docs.parse_mermaid("flowchart TD\nA-->B", str(self.root / "missing.mjs")), expected)

    @unittest.skipUnless(shutil.which("node"), "Node not installed; parser protocol tests need Node")
    def test_real_adapter_protocol_and_runtime_error_redaction(self):
        module = Path(self.temp.name) / "fake.mjs"
        template = ("export default { initialize(){}, async parse(text){ "
                    "if(text.startsWith('not_a_')){ let e=new Error('control');e.hash={};throw e;} "
                    "BODY } }; ")
        for body, diagram, expected in (
                ("return {diagramType:'flowchart'};", "flowchart TD\nX-->Y", "pass"),
                ("if(text.includes('secret')){let e=new Error(text);e.hash={};throw e;}return {};", "secret diagram", "invalid"),
                ("if(text.includes('secret')) throw new ReferenceError(text);return {};", "secret runtime", "unusable"),
                ("return undefined;", "anything", "unusable")):
            with self.subTest(expected=expected):
                module.write_text(template.replace("BODY", body))
                self.assertEqual(docs.parse_mermaid(diagram, str(module)), expected)
        module.write_text("export default {parse:async()=>true};")
        self.assertEqual(docs.parse_mermaid("bad", str(module)), "unusable")

    def test_parser_empty_output_and_timeout(self):
        for result in (subprocess.CompletedProcess([], 0, b"", b"secret"),
                       subprocess.CompletedProcess([], 0, b"PASS\nsecret", b"")):
            with patch.object(docs.shutil, "which", return_value="node"), patch.object(docs.subprocess, "run", return_value=result):
                self.assertEqual(docs.parse_mermaid("secret", None), "unusable")
        with patch.object(docs.shutil, "which", return_value="node"), patch.object(docs.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 30)):
            self.assertEqual(docs.parse_mermaid("secret", None), "unusable")

    def test_parser_private_module_refused_before_process(self):
        with patch.object(docs.subprocess, "run") as call:
            self.assertEqual(docs.parse_mermaid("safe", str(self.root / ".env.mjs")), "unusable")
            call.assert_not_called()

    def test_privacy_pass(self):
        self.assertEqual(self.check("# Ordinary fictional documentation\n")[0], 0)

    def test_privacy_pattern_and_key_bypass_value_free(self):
        value = "sk-" + "FictionalValue12345678901234567890"
        code, out = self.check("project-data/fixture\n" + value)
        self.assertEqual(code, 1)
        self.assertIn("privacy", out)
        self.assertNotIn(value, out)
        self.assertNotIn("project-data/fixture", out)

    def test_configurable_privacy_and_malformed_regex(self):
        self.assertEqual(self.check("fictional-sensitive", "--forbid", "fictional-sensitive")[0], 1)
        self.assertEqual(self.check("safe", "--forbid", "[")[0], 2)

    def test_hash_list_external_pass_and_fail_redacted(self):
        value = "Fictional Private Phrase"
        digest = hashlib.sha256(value.casefold().encode()).hexdigest()
        external = Path(self.temp.name) / "hashes.json"
        external.write_text(json.dumps({"version": 1, "entries": [{"words": 3, "sha256": digest}]}))
        with patch.dict(os.environ, {"DOCS_PRIVATE_HASHES": str(external)}):
            self.assertEqual(self.check("ordinary words")[0], 0)
            code, out = self.check(value.upper())
            self.assertEqual(code, 1)
            self.assertNotIn(value.upper(), out)
            self.assertIn("private_hash", out)
            self.assertEqual(self.check("Ｆｉｃｔｉｏｎａｌ\tPrivate  Phrase")[0], 1)
            self.assertEqual(self.check("Fictional Private Phrase.")[0], 0)

    def test_hash_list_field_matrix(self):
        external = Path(self.temp.name) / "hashes.json"
        valid = {"words": 1, "sha256": "a" * 64}
        cases = [{**valid, "words": value} for value in (None, True, 1.0, "1", 0, 33)]
        cases += [{**valid, "sha256": value} for value in (None, "", "A" * 64, "a" * 63, "a" * 64 + "\n")]
        cases += [{"words": 1}, {**valid, "extra": 1}]
        for row in cases:
            with self.subTest(row=row), patch.dict(os.environ, {"DOCS_PRIVATE_HASHES": str(external)}):
                external.write_text(json.dumps({"version": 1, "entries": [row]}))
                self.assertEqual(self.check("safe")[0], 2)

    def test_hash_list_unset_inside_repo_missing_malformed(self):
        with patch.dict(os.environ, {"DOCS_PRIVATE_HASHES": ""}):
            self.assertIn("private_hashes=disabled", self.check("safe")[1])
        for path in (self.root / "hash.json", Path(self.temp.name) / "absent.json"):
            with patch.dict(os.environ, {"DOCS_PRIVATE_HASHES": str(path)}):
                self.assertEqual(self.check("safe")[0], 2)
        external = Path(self.temp.name) / "hash.json"
        for text in ("invalid", '{"version":1,"entries":[{"words":true,"sha256":"abc"}]}',
                     '{"version":1,"entries":[]}'):
            external.write_text(text)
            with patch.dict(os.environ, {"DOCS_PRIVATE_HASHES": str(external)}):
                self.assertEqual(self.check("safe")[0], 2)

    def test_privacy_exit_two_retains_findings(self):
        with patch.object(docs, "parse_mermaid", return_value="unavailable"):
            code, out = self.check("project-data\n```mermaid\nflowchart TD\n```\n")
            self.assertEqual(code, 2)
            self.assertIn("privacy", out)

    def test_newline_pass(self):
        self.assertEqual(self.check("changed text\n", "--base", self.old)[0], 0)

    def test_newline_only_bypass(self):
        code, out = self.check(b"# Page\r\n", "--base", self.old)
        self.assertEqual(code, 1)
        self.assertIn("newline_change", out)
        self.assertIn("content_equal=yes", out)

    def test_mixed_newlines_and_missing_base(self):
        code, out = self.check(b"one\nsecond\r\n", "--base", self.old)
        self.assertEqual(code, 1)
        self.assertIn("mixed", out)
        self.assertEqual(self.check("safe", "--base", "missing")[0], 2)

    def test_revision_uses_git_bytes_not_worktree(self):
        self.write("docs/page.md", "[broken](missing)")
        self.assertEqual(self.check(None, "--revision", self.old)[0], 0)

    def test_revision_missing_wrong_type_and_option(self):
        blob = self.git("rev-parse", "HEAD:src/file.py")
        for revision in ("missing", blob, "--help", self.old + "\n"):
            with self.subTest(revision=revision):
                code, out = self.check(None, "--revision=" + revision)
                self.assertEqual(code, 2, out)

    def test_missing_selected_pages_and_empty_selection(self):
        self.assertEqual(self.check(None, "--page", "docs/missing.md")[0], 2)
        self.assertEqual(self.check(None, "--page", "missing-dir")[0], 2)

    def test_unsafe_paths_rejected_before_access(self):
        paths = ["../.env", "../.ENV.example", "../../outside.md", "C:/x", "//server/share",
                 "../data/x", "../project-data/x", "../poc-catalog/x", "../src/x:ads",
                 "../src/file.py.", "../src/file.py%20", "../src/%252eenv", "../src/a~1.py",
                 "../src/a%00b", "../src/a%5Cb", "../src/a%20/b", "../src/CON"]
        for target in paths:
            with self.subTest(target=target):
                code, out = self.check(f"[secret]({target})")
                self.assertNotEqual(code, 0, out)

    def test_private_paths_not_read_even_through_link(self):
        read = Path.read_bytes
        seen = []
        def guarded(path):
            seen.append(path.as_posix())
            if any(p.casefold().startswith(".env") or p.casefold() in docs.BLOCKED for p in path.parts):
                self.fail("private path was opened")
            return read(path)
        with patch.object(Path, "read_bytes", guarded):
            self.assertEqual(self.check("[private](../.env.hidden)")[0], 2)
        self.assertFalse(any(".env" in p for p in seen))

    def test_root_private_path_refused_before_git(self):
        with patch.object(docs.subprocess, "run") as call:
            with self.assertRaises(docs.CannotVerify):
                docs.Tree(self.root / "data")
            call.assert_not_called()

    def test_local_reparse_point_refused_before_read(self):
        target = self.root / "src" / "file.py"
        original = Path.lstat
        def alias_stat(path):
            stat = original(path)
            if path == target:
                return SimpleNamespace(st_file_attributes=0x400, st_mode=stat.st_mode)
            return stat
        with patch.object(Path, "lstat", alias_stat):
            self.assertEqual(self.check("[source](../src/file.py#L1)")[0], 2)

    def test_binary_line_target_not_read(self):
        self.write("src/fictional.pdf", b"not a real document")
        read = Path.read_bytes
        def guarded(path):
            if path.suffix == ".pdf":
                self.fail("binary target read")
            return read(path)
        with patch.object(Path, "read_bytes", guarded):
            self.assertEqual(self.check("[line 1](../src/fictional.pdf#L1)")[0], 2)

    def test_git_submodule_not_followed(self):
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.old + ",src/module")
        self.git("commit", "-qm", "module fixture")
        sha = self.git("rev-parse", "HEAD")
        self.assertEqual(self.check(self.link(sha=sha, target="src/module/README.md", anchor="", label="source"))[0], 2)

    def test_html_links_explicitly_unverified(self):
        self.assertEqual(self.check('<a href="../src/file.py">source</a>')[0], 2)

    def test_git_selected_alias_refused(self):
        oid = self.git("rev-parse", "HEAD:src/file.py")
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",docs/alias.md")
        self.git("commit", "-qm", "alias fixture")
        sha = self.git("rev-parse", "HEAD")
        self.assertEqual(self.check(None, "--revision", sha, "--page", "docs")[0], 2)

    def test_git_symlink_not_followed(self):
        oid = subprocess.check_output(["git", "-C", str(self.root), "hash-object", "-w", "--stdin"],
                                      input=b"../.env").decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",src/alias")
        self.git("commit", "-qm", "symlink fixture")
        sha = self.git("rev-parse", "HEAD")
        code, out = self.check(self.link(sha=sha, target="src/alias", anchor="", label="source"))
        self.assertEqual(code, 2)
        self.assertIn("unsafe", out)

    def test_git_symlink_parent_not_followed(self):
        oid = self.git("rev-parse", "HEAD:src/file.py")
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",alias")
        self.git("commit", "-qm", "alias fixture")
        sha = self.git("rev-parse", "HEAD")
        self.assertEqual(self.check(self.link(sha=sha, target="alias/file.py", anchor="", label="source"))[0], 2)

    def test_entrypoint_process_and_bad_cli(self):
        command = [sys.executable, str(HERE / "check_docs.py"), "--repo", str(self.root), "--page", "docs/page.md"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.write("docs/page.md", "[broken](missing)\n")
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        result = subprocess.run(command + ["--page", "docs/missing.md"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        result = subprocess.run(command + ["--unknown"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


class MutationTests(unittest.TestCase):
    def test_each_removed_check_is_detected_by_its_defect_test(self):
        cases = {
            "check_link": "test_broken_link_bypass",
            "check_anchor": "test_anchor_bounds_and_label_bypass",
            "check_pins": "test_pin_changed_blob_bypass",
            "check_diagram": "test_mermaid_pass_and_fail_with_injected_parser",
            "check_privacy": "test_privacy_pattern_and_key_bypass_value_free",
            "check_newlines": "test_newline_only_bypass",
        }
        for method, test in cases.items():
            with self.subTest(check=method), patch.object(docs.Checker, method, lambda *args: None):
                result = unittest.TestResult()
                CheckerTests(test).run(result)
                self.assertEqual(len(result.errors), 0, result.errors)
                self.assertGreater(len(result.failures), 0, "Removed check escaped its regression")


if __name__ == "__main__":
    unittest.main()
