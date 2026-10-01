"""Normalization v1: NFKC, strip, casefold region/category; strict ISO dates.

Rows are classified in field order: id, region, category, quantity, cents, date.
Quantity is nonnegative; cents are signed. Null/blank or malformed fields are
invalid rows. Aggregate overflow fails the partition, never wraps or uses floats.
"""

import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

INPUT_SCHEMA = pa.schema([
    ("record_id", pa.string()), ("customer_region", pa.string()), ("category", pa.string()),
    ("quantity", pa.int64()), ("amount_cents", pa.int64()), ("event_date", pa.string()),
])
OUTPUT_SCHEMA = pa.schema([pa.field(name, kind, nullable=False) for name, kind in (
    ("customer_region", pa.string()), ("category", pa.string()), ("event_date", pa.string()),
    ("record_count", pa.int64()), ("quantity_sum", pa.int64()), ("amount_cents_sum", pa.int64()),
)])


def schema_hash(schema):
    description = [(field.name, str(field.type), field.nullable) for field in schema]
    return hashlib.sha256(json.dumps(description, separators=(",", ":")).encode()).hexdigest()


INPUT_SCHEMA_HASH = schema_hash(INPUT_SCHEMA)
OUTPUT_SCHEMA_HASH = schema_hash(OUTPUT_SCHEMA)
# Bind the deployed identity to this actual implementation, schema and rules.
WORKLOAD_DIGEST = "sha256:" + hashlib.sha256(Path(__file__).read_text(encoding="utf-8").encode()).hexdigest()
WORKLOAD = {"name": "normalize_aggregate", "version": "1", "digest": WORKLOAD_DIGEST}


class WorkloadError(ValueError):
    pass


def read_parquet(source, schema):
    try:
        table = pq.read_table(source)
    except (pa.ArrowException, OSError, ValueError) as error:
        raise WorkloadError("invalid_parquet") from error
    if not table.schema.equals(schema, check_metadata=False):
        raise WorkloadError("schema_mismatch")
    if any(not field.nullable and column.null_count for field, column in zip(schema, table.columns)):
        raise WorkloadError("schema_nullability")
    return table


def write_parquet(table, destination):
    pq.write_table(table, destination, version="2.6", compression="NONE", use_dictionary=False,
                   write_statistics=True, row_group_size=65536)


def normalize(value):
    return unicodedata.normalize("NFKC", value).strip() if value is not None else ""


def execute(tables):
    groups = {}
    counters = Counter(input_rows=0, valid_rows=0, invalid_rows=0)
    reasons = Counter()
    for table in tables:
        if not table.schema.equals(INPUT_SCHEMA, check_metadata=False):
            raise WorkloadError("schema_mismatch")
        for row in table.to_pylist():
            counters["input_rows"] += 1
            region, category, day = (normalize(row[k]) for k in ("customer_region", "category", "event_date"))
            reason = None
            if not normalize(row["record_id"]): reason = "invalid_record_id"
            elif not region: reason = "invalid_region"
            elif not category: reason = "invalid_category"
            elif row["quantity"] is None or row["quantity"] < 0: reason = "invalid_quantity"
            elif row["amount_cents"] is None: reason = "invalid_amount"
            else:
                try:
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day): raise ValueError
                    date.fromisoformat(day)
                except ValueError:
                    reason = "invalid_date"
            if reason:
                counters["invalid_rows"] += 1
                reasons[reason] += 1
                continue
            counters["valid_rows"] += 1
            key = (region.casefold(), category.casefold(), day)
            previous = groups.get(key, (0, 0, 0))
            total = (previous[0] + 1, previous[1] + row["quantity"], previous[2] + row["amount_cents"])
            for number, code in zip(total, ("count_overflow", "quantity_overflow", "cents_overflow")):
                if not -(1 << 63) <= number < (1 << 63): raise WorkloadError(code)
            groups[key] = total
    rows = [dict(zip(OUTPUT_SCHEMA.names, key + groups[key])) for key in sorted(groups)]
    return pa.Table.from_pylist(rows, schema=OUTPUT_SCHEMA), dict(counters) | {"invalid_reasons": dict(sorted(reasons.items()))}
