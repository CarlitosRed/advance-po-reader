"""Local fictional .eml intake. --live is opt-in and requires --ledger."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from email_intake.ledger import LedgerError, SpendLedger, safe_path
from email_intake.providers import FakeProvider, LiveProvider
from email_intake.locking import LockError
from email_intake.runner import run
from email_intake.senders import SenderListError, load as load_senders


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drop", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--break-lock", action="store_true", help="Recover a stale lock only when its owner is provably gone")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--ledger", type=Path, help="One shared classifier spend ledger for all phase-one runs")
    ap.add_argument("--init-ledger", action="store_true", help="Create a missing or recover a zero-byte ledger; never reset spend history")
    ap.add_argument("--fake-results", type=Path, help="Offline only: trusted JSON map of original SHA to classifier result")
    ap.add_argument("--known-senders", type=Path, help="Optional exact address/domain list; unknown senders require review")
    args = ap.parse_args(argv)
    try:
        known_senders = load_senders(args.known_senders) if args.known_senders is not None else None
        if args.init_ledger and (not args.live or args.ledger is None):
            print(json.dumps({"reason_code": "LEDGER"}))
            return 2
        if args.live:
            if args.ledger is None or args.fake_results is not None:
                print(json.dumps({"reason_code": "LEDGER"}))
                return 2
            ledger_path = safe_path(args.ledger).resolve()
            print(json.dumps({"ledger": str(ledger_path), "init_ledger": args.init_ledger}), file=sys.stderr)
            ledger = SpendLedger(ledger_path, initialize=args.init_ledger)
            provider = LiveProvider(enabled=True, api_key=os.environ.get("OPENAI_API_KEY"), ledger=ledger)
        else:
            results = {}
            if args.fake_results:
                results = json.loads(safe_path(args.fake_results).read_text(encoding="utf-8"))
                if not isinstance(results, dict):
                    raise ValueError("INVALID")
            provider = FakeProvider(results)
        results = run(args.drop, args.out, provider, break_lock=args.break_lock,
                      report=lambda message: print(json.dumps(message), file=sys.stderr),
                      known_senders=known_senders)
        for result in results:
            print(json.dumps(result))
        if args.live and results and all(result["reused"] for result in results):
            print(json.dumps({"warning": "ALL_REUSED", "hint": "All emails reused stored outcomes; no new classification was attempted."}), file=sys.stderr)
        return 0
    except SenderListError:
        print(json.dumps({"reason_code": "UNKNOWN_SENDER", "hint": "Use a non-empty UTF-8 list of exact addresses or domains."}))
        return 2
    except LockError:
        print(json.dumps({"reason_code": "CONFLICT", "hint": "Intake is locked. --break-lock recovers only a dead owner; active or unknown owners refuse."}))
        return 2
    except LedgerError:
        print(json.dumps({"reason_code": "LEDGER", "hint": "Use an existing ledger or --init-ledger for first use"}))
        return 2
    except (ValueError, OSError):
        # No path, key, source content or exception prose in notifications.
        print(json.dumps({"reason_code": "CONFLICT"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
