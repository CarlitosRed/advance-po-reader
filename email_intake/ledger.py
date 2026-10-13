"""SQLite spend reservations in integer nanodollars, committed before transport.

One shared ledger for the entire fictional phase is mandatory. This ledger covers
classifier calls only; it does not authorize reader spending. Unknown outcomes
retain their entire reservation. No reset/release command is provided.
"""
import json
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import uuid

CAP_NANO = 3_000_000_000
INPUT_BOUND = 6000
OUTPUT_BOUND = 100
# Verified Standard Luna write/input upper rate and output rate, 2026-10-08.
INPUT_RATE = 125
OUTPUT_RATE = 500
RESERVATION = INPUT_BOUND * INPUT_RATE + OUTPUT_BOUND * OUTPUT_RATE


class LedgerError(ValueError):
    pass


def safe_path(path):
    """Reject symlinks/junctions, including existing ancestor aliases."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.stat(), "st_file_attributes", 0) & 1024):
            raise LedgerError("LEDGER")
    if path.name.lower().startswith(".env"):
        raise LedgerError("LEDGER")
    return path


class SpendLedger:
    def __init__(self, path, *, initialize=False):
        self.path = safe_path(path).resolve()
        if not self.path.parent.is_dir():
            raise LedgerError("LEDGER")
        if not self.path.exists():
            if not initialize:
                raise LedgerError("LEDGER")
            try:
                # Exclusive creation cannot overwrite an existing spend history.
                with self.path.open("xb"):
                    pass
            except FileExistsError:
                pass
        try:
            # A zero-byte primary with recovery sidecars may contain prior spend.
            # Do not let SQLite open/recover it as a fresh cap.
            if self.path.stat().st_size == 0:
                for suffix in ("-journal", "-wal", "-shm"):
                    sidecar = safe_path(str(self.path) + suffix)
                    if sidecar.exists() and sidecar.stat().st_size:
                        raise LedgerError("LEDGER")
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                expected = json.dumps([1, CAP_NANO, INPUT_BOUND, OUTPUT_BOUND, INPUT_RATE, OUTPUT_RATE])
                # Recheck inside the transaction so concurrent initializers can
                # only create once. Never reset a non-empty/corrupt database.
                if initialize and self.path.stat().st_size == 0:
                    db.execute("CREATE TABLE policy (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
                    db.execute("INSERT INTO policy VALUES (1, ?)", (expected,))
                    db.execute("""CREATE TABLE attempts (
                        id TEXT PRIMARY KEY, intake_id TEXT NOT NULL, charge INTEGER NOT NULL CHECK(charge>=0),
                        state TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
                        reason_code TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
                if db.execute("SELECT value FROM policy WHERE id=1").fetchone() != (expected,):
                    raise LedgerError("LEDGER")
                db.execute("SELECT id FROM attempts LIMIT 1")
        except sqlite3.Error:
            raise LedgerError("LEDGER") from None

    @contextmanager
    def connect(self):
        safe_path(self.path)
        # mode=rw refuses a deleted/mistyped file even after construction; only
        # explicit initialization above may create a new cap.
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, intake_id):
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT 1 FROM attempts WHERE intake_id=? LIMIT 1", (intake_id,)).fetchone():
                    raise LedgerError("TRANSPORT_PENDING")
                total = db.execute("SELECT COALESCE(SUM(charge),0) FROM attempts").fetchone()[0]
                if type(total) is not int or total < 0 or total + RESERVATION > CAP_NANO:
                    raise LedgerError("CAP")
                aid = uuid.uuid4().hex
                db.execute("INSERT INTO attempts(id,intake_id,charge,state) VALUES(?,?,?,'reserved')",
                           (aid, intake_id, RESERVATION))
                return aid
        except sqlite3.Error:
            raise LedgerError("LEDGER") from None

    def finish(self, aid, usage, reason):
        valid = (isinstance(usage, dict) and type(usage.get("input_tokens")) is int
                 and type(usage.get("output_tokens")) is int
                 and 0 <= usage["input_tokens"] <= INPUT_BOUND
                 and 0 <= usage["output_tokens"] <= OUTPUT_BOUND)
        charge = usage["input_tokens"] * INPUT_RATE + usage["output_tokens"] * OUTPUT_RATE if valid else RESERVATION
        try:
            with self.connect() as db:
                db.execute("UPDATE attempts SET charge=?,state=?,input_tokens=?,output_tokens=?,reason_code=? WHERE id=? AND state='reserved'",
                           (charge, "settled" if valid else "unknown", usage.get("input_tokens") if valid else None,
                            usage.get("output_tokens") if valid else None, reason, aid))
        except sqlite3.Error:
            raise LedgerError("LEDGER") from None
        return valid
