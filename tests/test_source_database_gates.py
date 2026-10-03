"""Focused safeguards for the private source-database staging schema."""
from __future__ import annotations

import sqlite3
import unittest

from scripts.build_source_databases import init_pdf_db


def _seed_two_page_document(conn: sqlite3.Connection) -> tuple[str, str]:
    archive_sha = "a" * 64
    source_sha = "b" * 64
    conn.execute(
        "INSERT INTO source_archives VALUES(?,?,?,?,?)",
        ("archive", "orders.zip", archive_sha, 8, "test fixture"),
    )
    conn.execute(
        """INSERT INTO source_documents VALUES
        (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            source_sha, "D01", "order.pdf", "order.pdf", "[]", "application/pdf",
            8, 2, archive_sha, b"%PDF-test", None, None,
            "pending_human_review", 0,
        ),
    )
    for page_number in (1, 2):
        image_sha = str(page_number) * 64
        rgb_sha = str(page_number + 2) * 64
        conn.execute(
            "INSERT INTO page_media VALUES(?,?,?,?,?,?)",
            (image_sha, rgb_sha, 1, 1, "image/png", b"png" + bytes([page_number])),
        )
        conn.execute(
            """INSERT INTO document_pages VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_sha, page_number, f"D01-P{page_number}", str(page_number + 4) * 64,
                "test", image_sha, rgb_sha, "test", 72, 1, 1, "", "c" * 64, 0,
                "{}", "d" * 64, "e" * 64, "human_review_candidate", None, None,
                None, "candidate", "pending_human_review", 0,
            ),
        )
    return source_sha, archive_sha


def _approve_page(conn: sqlite3.Connection, source_sha: str, page_number: int) -> None:
    conn.execute(
        """INSERT INTO human_review_events VALUES
        (?,?,?,?,?,?,?,?,?,?)""",
        (
            f"review-{page_number}", source_sha, page_number, "Reviewer One", "approve",
            "2026-10-02T00:00:00Z", "Checked against the page image", None, None, "{}",
        ),
    )


class SourceDatabaseGateTests(unittest.TestCase):
    def test_training_view_requires_named_approval_for_every_page(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        init_pdf_db(conn)
        source_sha, _ = _seed_two_page_document(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM approved_training_examples").fetchone()[0], 0)

        conn.execute(
            "UPDATE source_documents SET review_status='human_approved',training_eligible=1"
        )
        conn.execute(
            "UPDATE document_pages SET review_status='human_approved',training_eligible=1"
        )
        _approve_page(conn, source_sha, 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM approved_training_examples").fetchone()[0], 0)

        _approve_page(conn, source_sha, 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM approved_training_examples").fetchone()[0], 2)

    def test_review_events_are_append_only(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        init_pdf_db(conn)
        source_sha, _ = _seed_two_page_document(conn)
        _approve_page(conn, source_sha, 1)

        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            conn.execute("UPDATE human_review_events SET reason='rewritten' WHERE event_id='review-1'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            conn.execute("DELETE FROM human_review_events WHERE event_id='review-1'")
