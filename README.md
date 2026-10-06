# Open Food Facts import module

## Unknown Data loader

The first ingestion stage reads supported raw files into a pandas DataFrame.
It returns the table, source filename, format, warnings, and a small JSON preview.
Field mapping, unit conversion, product validation, and website integration belong
to subsequent components and are not implemented here.

### Setup and demo

Requires Python 3.11+ and uv. Development is tested with Python 3.12.

```bash
uv sync --frozen
make demo
uv run unknown-data examples/products.json --records-key products
uv run unknown-data examples/products.jsonl
uv run unknown-data examples/products.xml
uv run unknown-data examples/broken.csv
```

The last command intentionally exits with status 1 and a line-numbered error.
Example data is synthetic. Use `make demo` for the loader; the original `make run`
target remains a starter placeholder.

### Python interface

```python
from unknown_data import LoadError, LoadOptions, load_file

try:
    result = load_file("examples/products.csv")
    dataframe = result.dataframe  # pass to the next transformation stage
    preview = result.preview()  # JSON-compatible dict for a future web endpoint
except LoadError as exc:
    error = {"code": exc.code, "message": str(exc)}
```

Use `LoadOptions(records_path=("products",))` for a JSON wrapper; multiple keys
select a nested wrapper. CSV delimiter and encoding can be supplied explicitly:
`LoadOptions(delimiter=";", encoding="cp1252")`.

### Supported inputs and behavior

| Format | Accepted structure |
| --- | --- |
| CSV/TSV | Header with unique, nonempty names; equal-width rows; quoted and multiline fields |
| JSON | Array of objects, or explicit path to a wrapped array |
| JSONL/NDJSON | One object per nonblank line |
| XML | Root container with same-tag record children; no container metadata or mixed text |

CSV and XML values remain strings, preserving barcode leading zeroes. JSON retains
source types. Missing JSON/XML fields produce missing cells and a warning. A later
mapping stage should apply field-specific type conversions.

Nested object fields become dotted columns such as `nutrition.sugar_100g`.
Lists and empty nested objects stay in cells. Literal dots in JSON/XML keys are
rejected to avoid ambiguous paths; CSV header dots are allowed. XML attributes use
`@` prefixes. Namespace-qualified tags containing dots may hit this restriction.

Known extensions choose a parser. Unknown extensions use limited JSON/XML content
detection; specify `--format` for other cases. The loader does not guess arbitrary
schemas or encodings. UTF-8 with or without a BOM is the default; explicitly select
other encodings, including for XML. Wrapped JSON does not silently discard metadata:
the caller explicitly selects the records array to import.

### Errors and limitations

The complete file is rejected on a parsing error; bad rows are not silently skipped.
`LoadError.code` distinguishes file, size, encoding, format, header, parsing, shape,
empty-input, nesting, row-limit, column-limit, and options errors. The CLI returns
JSON errors on stderr and exit code 1; successful previews go to stdout with code 0.

Defaults: 10 MiB file size, 100,000 records, 1,000 columns, nesting depth 32. This is
an in-memory prototype, not a streaming importer. Python objects can use much more
RAM than source bytes; production workers also need memory and time limits.
Python's CSV parser has a separate field-size limit. XML DTDs/entities are rejected
using defusedxml. ZIP, Excel, Parquet, remote downloads and supplier-specific XML
adapters are not implemented.

Preview JSON is for display, not an exact archival round trip: floats can be rounded
and JavaScript cannot represent every large integer exactly. Identifiers should be
strings. The Python DataFrame is the handoff to subsequent processing.

A future upload endpoint should save files to a controlled temporary location and
call `load_file`; browser users should not choose arbitrary server filesystem paths.
The actual upload endpoint and frontend are outside this module.

### Checks

```bash
make lint
make lint-strict
make test
uv run ruff format --check src/unknown_data tests
```

Pull-request CI runs lint, strict type checking, and tests. Tests cover supported
formats, identifier preservation, nested data, malformed files, encoding, XML
entities, and configured limits. They use synthetic fixtures; real supplier samples
and the team's downstream contract still need integration testing.

### Layout

- `src/unknown_data/loader.py`: public loader, options, parsers, errors, result.
- `src/unknown_data/__main__.py`: CLI interface.
- `tests/test_loader.py`: behavioral tests.
- `examples/`: synthetic input files and a malformed-file demo.

Dependency versions are recorded in `uv.lock`. After changing dependencies, run
`uv sync` and commit the updated lockfile alongside `pyproject.toml`.
