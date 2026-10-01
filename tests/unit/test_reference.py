import io
import random

import pyarrow as pa
import pytest

from relay.workloads.reference import INPUT_SCHEMA, OUTPUT_SCHEMA, WorkloadError, execute, read_parquet, write_parquet

from .oracle import serial_oracle


def fixture_rows(count=48):
    generator = random.Random(20261002)
    rows = [dict(record_id=str(i), customer_region=generator.choice([" EU ", "Ｓouth", "Straße", "STRASSE"]),
                 category=generator.choice([" Book ", "FOOD", "food"]), quantity=generator.randrange(4),
                 amount_cents=generator.randrange(-500, 1000), event_date=f"2024-01-{1+i%3:02d}") for i in range(count)]
    bad = [("record_id", None), ("customer_region", "  "), ("category", None), ("quantity", -1),
           ("amount_cents", None), ("event_date", "2024-02-30")]
    for i in range(0, count, 7):
        field, value = bad[(i//7) % len(bad)]; rows[i][field] = value
    return rows


def test_reference_against_independent_serial_oracle():
    rows = fixture_rows()
    result, counters = execute([pa.Table.from_pylist(rows[:20], schema=INPUT_SCHEMA), pa.Table.from_pylist(rows[20:], schema=INPUT_SCHEMA)])
    expected, expected_counts = serial_oracle(rows)
    assert result.to_pylist() == expected
    assert counters == expected_counts
    assert result.schema == OUTPUT_SCHEMA
    buffers = [io.BytesIO(), io.BytesIO()]
    for buffer in buffers: write_parquet(result, buffer)
    assert buffers[0].getvalue() == buffers[1].getvalue()
    assert read_parquet(pa.BufferReader(buffers[0].getvalue()), OUTPUT_SCHEMA).to_pylist() == expected


def test_empty_partition():
    output, counts = execute([pa.Table.from_pylist([], schema=INPUT_SCHEMA)])
    assert output.num_rows == 0 and output.schema == OUTPUT_SCHEMA
    assert counts == {"input_rows": 0, "valid_rows": 0, "invalid_rows": 0, "invalid_reasons": {}}


@pytest.mark.parametrize("field,error", [("amount_cents", "cents_overflow"), ("quantity", "quantity_overflow")])
def test_checked_integer_overflow(field, error):
    row = dict(record_id="1", customer_region="EU", category="book", quantity=1, amount_cents=1, event_date="2024-01-01")
    rows = [row | {field: 2**63-1}, row]
    with pytest.raises(WorkloadError, match=error): execute([pa.Table.from_pylist(rows, schema=INPUT_SCHEMA)])
    with pytest.raises(OverflowError): serial_oracle(rows)


@pytest.mark.parametrize("day", ["20240101", "2024-1-01", "2024-01-1", "2024-W01-1", "2023-02-29"])
def test_strict_iso_date(day):
    row = fixture_rows(2)[1] | {"event_date": day}
    output, counts = execute([pa.Table.from_pylist([row], schema=INPUT_SCHEMA)])
    assert output.num_rows == 0 and counts["invalid_reasons"] == {"invalid_date": 1}
