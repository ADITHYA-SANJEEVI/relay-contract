"""Independent serial semantics; does not call production normalization/reducer."""

import unicodedata
from collections import defaultdict
from datetime import date


def serial_oracle(rows):
    groups = defaultdict(list)
    reasons = defaultdict(int)
    for record in rows:
        strings = {key: unicodedata.normalize("NFKC", record[key] or "").strip()
                   for key in ("record_id", "customer_region", "category", "event_date")}
        bad = None
        for key, reason in (("record_id", "invalid_record_id"), ("customer_region", "invalid_region"), ("category", "invalid_category")):
            if not strings[key]: bad = reason; break
        if bad is None and (record["quantity"] is None or record["quantity"] < 0): bad = "invalid_quantity"
        if bad is None and record["amount_cents"] is None: bad = "invalid_amount"
        if bad is None:
            day = strings["event_date"]
            try:
                if len(day) != 10 or day[4] != "-" or day[7] != "-" or not (day[:4]+day[5:7]+day[8:]).isascii():
                    raise ValueError
                parsed = date(int(day[:4]), int(day[5:7]), int(day[8:]))
                if parsed.isoformat() != day: raise ValueError
            except ValueError: bad = "invalid_date"
        if bad:
            reasons[bad] += 1
        else:
            groups[(strings["customer_region"].casefold(), strings["category"].casefold(), strings["event_date"])].append(record)
    result = []
    for (region, category, day), records in sorted(groups.items()):
        count, quantity, cents = len(records), sum(r["quantity"] for r in records), sum(r["amount_cents"] for r in records)
        if any(value < -(2**63) or value > 2**63-1 for value in (count, quantity, cents)): raise OverflowError
        result.append(dict(customer_region=region, category=category, event_date=day,
                           record_count=count, quantity_sum=quantity, amount_cents_sum=cents))
    invalid = sum(reasons.values())
    return result, dict(input_rows=len(rows), valid_rows=len(rows)-invalid,
                       invalid_rows=invalid, invalid_reasons=dict(sorted(reasons.items())))
