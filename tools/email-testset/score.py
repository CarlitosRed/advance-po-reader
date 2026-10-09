"""Score complete JSONL predictions against fictional email ground truth.

Exit 0: no orders labelled no; 1: at least one lost order; 2: invalid input.
No model calls or automatic answers. Rates are fractions; undefined rates are null.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from email_testset_contract import CATEGORY_LANE, CATEGORY_REASON, LANGUAGES, LANES, MUTATIONS


class InvalidInput(ValueError):
    pass


def closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidInput(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise InvalidInput(f"non-JSON constant: {value}")


def require(condition, message):
    if not condition:
        raise InvalidInput(message)


def read_rows(path, expected):
    rows = {}
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            where = f"{path}:{number}"
            try:
                row = json.loads(line, object_pairs_hook=closed_object, parse_constant=invalid_constant)
                validate_row(row, expected)
                require(row["id"] not in rows, "duplicate id")
            except (ValueError, TypeError) as exc:
                raise InvalidInput(f"{where}: {exc}") from exc
            rows[row["id"]] = row
    require(bool(rows), f"{path}: empty file")
    return rows


def validate_row(row, expected):
    require(type(row) is dict, "each line must be an object")
    core = {"id", "category", "lane"}
    fields = core | {"where_order", "number_of_orders", "language", "mutation_tags", "sha256"} if expected else core
    optional = set() if expected else {"reason_code"}
    require(fields <= row.keys() <= fields | optional, "missing or unknown fields")
    require(type(row["id"]) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", row["id"]) is not None, "invalid id")
    category, lane = row["category"], row["lane"]
    require(type(category) is str and category in CATEGORY_LANE, "invalid category")
    require(type(lane) is str, "invalid lane")
    # 'no' is the task's short name for not_an_order; expected files use only
    # the design's canonical vocabulary. Do not silently normalize other text.
    if not expected and lane == "no":
        lane = row["lane"] = "not_an_order"
    require(lane == CATEGORY_LANE[category], "inconsistent category/lane pair")
    if "reason_code" in row:
        require(row["reason_code"] == CATEGORY_REASON[category], "inconsistent reason_code")
    if not expected:
        return
    require(type(row["language"]) is str and row["language"] in LANGUAGES, "invalid language")
    count = row["number_of_orders"]
    require(type(count) is int and count >= 0, "number_of_orders must be a nonnegative integer, not bool")
    require((count > 0) == (category == "order"), "order count disagrees with category")
    sources = row["where_order"]
    require(type(sources) is dict and sources.keys() == {"body", "attachments"}, "invalid where_order")
    require(type(sources["body"]) is bool and type(sources["attachments"]) is list, "invalid order sources")
    names = sources["attachments"]
    require(all(type(name) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", name) is not None
                and ".." not in name for name in names), "invalid attachment name")
    require(len(names) == len(set(names)), "duplicate attachment source")
    require(bool(sources["body"] or names) == (count > 0), "order locations disagree with order count")
    tags = row["mutation_tags"]
    require(type(tags) is list and bool(tags), "mutation_tags must be a nonempty list")
    require(all(type(tag) is str and tag in MUTATIONS for tag in tags), "invalid mutation tag")
    require(len(tags) == len(set(tags)), "duplicate mutation tag")
    require(type(row["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "invalid sha256")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def score(expected, answers):
    require(expected.keys() == answers.keys(), "answer ids must exactly match expected ids (no missing or extra answers)")
    categories = tuple(CATEGORY_LANE)
    confusion = {true: dict.fromkeys(categories, 0) for true in categories}
    lanes = {true: dict.fromkeys(LANES, 0) for true in LANES}
    true_orders = predicted_orders = correct_orders = safe_orders = 0
    total_order_count = direct_order_count = safe_order_count = 0
    lost = []
    for fixture_id, truth in expected.items():
        answer = answers[fixture_id]
        confusion[truth["category"]][answer["category"]] += 1
        lanes[truth["lane"]][answer["lane"]] += 1
        predicted_orders += answer["lane"] == "order"
        if truth["category"] != "order":
            continue
        true_orders += 1
        count = truth["number_of_orders"]
        total_order_count += count
        if answer["lane"] == "order":
            correct_orders += 1
            direct_order_count += count
        if answer["lane"] in ("order", "needs_a_look"):
            safe_orders += 1
            safe_order_count += count
        else:
            lost.append({"id": fixture_id, "number_of_orders": count})
    lost_orders = total_order_count - safe_order_count
    return {
        "emails": len(expected), "true_order_emails": true_orders,
        "number_of_orders": total_order_count, "predicted_order_emails": predicted_orders,
        "order_recall": ratio(correct_orders, true_orders),
        "order_or_needs_a_look_recall": ratio(safe_orders, true_orders),
        "order_precision": ratio(correct_orders, predicted_orders),
        "order_weighted_recall": ratio(direct_order_count, total_order_count),
        "order_weighted_safe_recall": ratio(safe_order_count, total_order_count),
        "lost_order_emails": len(lost), "lost_orders": lost_orders, "lost": lost,
        "pass_bar_met": true_orders >= 100 and lost_orders == 0,
        "category_confusion": confusion, "lane_confusion": lanes,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--answers", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        expected = read_rows(args.expected, expected=True)
        answers = read_rows(args.answers, expected=False)
        result = score(expected, answers)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 1 if result["lost_orders"] else 0


if __name__ == "__main__":
    sys.exit(main())
