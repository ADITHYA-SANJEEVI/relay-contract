# Reference normalization and Parquet format v1

This documents the concrete M1B implementation of SPEC.md's deterministic reference workload. It is partition-local; no global distributed reduction is implemented. The registry exposes `normalize_aggregate`, version `1`, and a `sha256:` digest of the actual reference implementation source with line endings normalized to LF. Submission and registration must match that deployed digest. PyArrow is pinned separately in the dependency lock. Parquet hashes identify actual bytes; semantic equality is checked by decoded rows.

## Canonical input

Fields in this order, all nullable to represent invalid records:

| Field | Arrow type |
|---|---|
| record_id | string |
| customer_region | string |
| category | string |
| quantity | int64 |
| amount_cents | int64 |
| event_date | string |

Canonical schema identity hashes compact JSON tuples `(name, type, nullable)` in field order. Import compares the declared schema hash with the deployed schema, parses exact stored Parquet bytes, and checks field order, types and nullability. An invalid file/schema never becomes VERIFIED. Media type is `application/vnd.apache.parquet`. Input import uses a configurable positive byte bound, default 256 MiB. No CSV conversion subsystem is included.

Input fixtures use Python `random.Random(20261002)`, fixed whitespace/case/full-width/Unicode variations, signed integer cents, and every seventh row invalid according to a deterministic field schedule. The fixture producer is `tests/unit/test_reference.py::fixture_rows`; `tests/integration/conftest.py::parquet_bytes` writes its canonical Parquet. These are test generators, not product job-submission functionality.

## Normalization and classification

Apply Unicode NFKC then Unicode whitespace trimming to text fields. Region/category additionally use Unicode casefolding. A date must normalize to exactly ASCII `YYYY-MM-DD` and be a valid Gregorian date; alternate ISO formats and impossible dates are rejected. Record ID is required but is not a grouping key or deduplication key. Duplicate input records remain distinct records.

Check each row in this fixed order and assign at most one invalid reason:

1. Missing/blank record ID: `invalid_record_id`.
2. Missing/blank region: `invalid_region`.
3. Missing/blank category: `invalid_category`.
4. Null/negative quantity: `invalid_quantity`.
5. Null cents: `invalid_amount`.
6. Malformed/impossible date: `invalid_date`.

Zero quantity and negative cents are valid. All numeric fields originate as int64, never floating point. Invalid rows contribute only to counters. Group valid rows by normalized region/category/date. Add integer record counts, quantity sums and signed cents sums in manifest slice/record order. Every aggregate addition checks signed 64-bit bounds; overflow raises a deterministic workload error and produces no output artifact. M1B does not settle that attempt's lifecycle.

## Output and counters

Sort groups lexicographically by region, category and ISO date. Output fields, all nonnullable:

| Field | Arrow type |
|---|---|
| customer_region | string |
| category | string |
| event_date | string |
| record_count | int64 |
| quantity_sum | int64 |
| amount_cents_sum | int64 |

Emit Parquet 2.6, uncompressed, dictionary encoding disabled, statistics enabled, row groups of 65,536. Empty slices yield the same schema with zero output rows. Counters are `input_rows`, `valid_rows`, `invalid_rows`, and a sorted `invalid_reasons` map; they are reported by the worker without raw record data. Numeric counters in HTTP contracts use decimal strings; local worker counters are JSON integers.

`tests/unit/oracle.py` independently normalizes/classifies records, collects groups and sums them serially; it does not call the production normalization or aggregation functions. Tests compare decoded canonical rows/counters and separately verify byte integrity. Quantity and cents overflow tests exercise both implementations. The oracle's serial sum is semantic validation, not a distributed reduce service.

The assigned-slice endpoint authenticates the recorded owner, reads and verifies the pinned whole input shard outside transactions, slices only its immutable manifest range, and sends canonical Parquet for that slice. The worker receives neither a whole-input download URL nor DB/S3 credentials. The gateway currently decodes a whole bounded shard per requested slice; large-shard performance and memory consumption have not been measured.
