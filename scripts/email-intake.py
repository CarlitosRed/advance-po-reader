"""Local fictional .eml intake. --live is opt-in and requires --ledger."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from email_intake.ledger import LedgerError, SpendLedger, safe_path
from email_intake.providers import FakeProvider, LiveProvider
from email_intake.runner import run


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drop", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--ledger", type=Path, help="One shared classifier spend ledger for all phase-one runs")
    ap.add_argument("--fake-results", type=Path, help="Offline only: trusted JSON map of original SHA to classifier result")
    args = ap.parse_args(argv)
    try:
        if args.live:
            if args.ledger is None or args.fake_results is not None:
                print(json.dumps({"reason_code": "LEDGER"}))
                return 2
            provider = LiveProvider(enabled=True, api_key=os.environ.get("OPENAI_API_KEY"),
                                    ledger=SpendLedger(args.ledger))
        else:
            results = {}
            if args.fake_results:
                results = json.loads(safe_path(args.fake_results).read_text(encoding="utf-8"))
                if not isinstance(results, dict):
                    raise ValueError("INVALID")
            provider = FakeProvider(results)
        for result in run(args.drop, args.out, provider):
            print(json.dumps(result))
        return 0
    except (ValueError, OSError, LedgerError):
        # No path, key, source content or exception prose in notifications.
        print(json.dumps({"reason_code": "CONFLICT"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
