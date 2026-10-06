"""Load supported, bounded local datasets without guessing product semantics."""

import csv
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import Element, ParseError

import pandas as pd
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

Format = Literal["csv", "json", "jsonl", "xml"]


class LoadError(ValueError):
    """An expected input failure with a stable code for a future web API."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class LoadOptions:
    """Explicit parsing choices and limits for the in-memory prototype."""

    format: Format | None = None
    encoding: str = "utf-8-sig"
    delimiter: str | None = None
    records_path: tuple[str, ...] = ()
    xml_record_tag: str | None = None
    max_bytes: int = 10 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 1_000
    max_depth: int = 32


@dataclass
class ImportResult:
    """The raw table plus provenance and nonfatal parsing notices."""

    dataframe: pd.DataFrame
    source_name: str
    format: Format
    warnings: list[str]

    def preview(self, limit: int = 5) -> dict[str, object]:
        """Return a small JSON-compatible payload for a CLI or future API."""
        if limit < 0 or limit > 100:
            raise ValueError("Preview limit must be between 0 and 100.")
        # pandas serializes absent values as JSON null.
        rows: object = json.loads(self.dataframe.head(limit).to_json(orient="records"))
        return {
            "source": self.source_name,
            "format": self.format,
            "row_count": len(self.dataframe),
            "columns": list(self.dataframe.columns),
            "warnings": self.warnings,
            "preview": rows,
        }


def _validate_options(options: LoadOptions) -> None:
    if (
        min(options.max_bytes, options.max_rows, options.max_columns, options.max_depth)
        < 1
    ):
        raise LoadError("options", "All limits must be positive integers.")
    if options.format not in (None, "csv", "json", "jsonl", "xml"):
        raise LoadError("options", "Supported formats: csv, json, jsonl, xml.")
    if options.delimiter is not None and (
        len(options.delimiter) != 1 or options.delimiter in '\r\n\x00"'
    ):
        raise LoadError("options", "Use a single delimiter other than a quote/newline.")


def _detect(path: Path, text: str, options: LoadOptions) -> Format:
    if options.format is not None:
        return options.format
    extensions: dict[str, Format] = {
        ".csv": "csv",
        ".tsv": "csv",
        ".json": "json",
        ".jsonl": "jsonl",
        ".ndjson": "jsonl",
        ".xml": "xml",
    }
    if path.suffix.lower() in extensions:
        return extensions[path.suffix.lower()]
    if text.lstrip().startswith(("{", "[")):
        return "json"
    if text.lstrip().startswith("<"):
        return "xml"
    raise LoadError("format", "Cannot identify format; set format explicitly.")


def _csv_records(
    text: str, path: Path, options: LoadOptions
) -> list[dict[str, object]]:
    delimiter = options.delimiter
    if delimiter is None:
        if path.suffix.lower() == ".tsv":
            delimiter = "\t"
        else:
            try:
                delimiter = (
                    csv.Sniffer().sniff(text[:65536], delimiters=",;\t|").delimiter
                )
            except csv.Error:
                delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header = next((row for row in reader if row), [])
        if not header or any(not name.strip() for name in header):
            raise LoadError("header", "CSV needs a nonempty name for every column.")
        if len(set(header)) != len(header):
            raise LoadError("header", "CSV contains duplicate column names.")
        if len(header) > options.max_columns:
            raise LoadError("columns", "CSV exceeds the column limit.")
        records: list[dict[str, object]] = []
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise LoadError(
                    "csv_row",
                    f"CSV line {reader.line_num}: expected {len(header)} "
                    f"fields, got {len(row)}. Check delimiter and quoting.",
                )
            records.append(dict(zip(header, row, strict=True)))
            if len(records) > options.max_rows:
                raise LoadError("rows", "Dataset exceeds the row limit.")
        return records
    except csv.Error as exc:
        raise LoadError(
            "csv", f"Invalid CSV near line {reader.line_num}: {exc}"
        ) from exc


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LoadError("json", f"Duplicate JSON key: {key!r}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise LoadError("json", f"Invalid JSON constant: {value}.")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise LoadError("json", "JSON number is outside the supported float range.")
    return number


def _parse_json(text: str, max_depth: int) -> object:
    try:
        value: object = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        pending: list[tuple[object, int]] = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > max_depth:
                raise LoadError("depth", "JSON exceeds the nesting limit.")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except json.JSONDecodeError as exc:
        raise LoadError(
            "json", f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc
    except LoadError:
        raise
    except ValueError as exc:
        raise LoadError(
            "json", "JSON contains a number the parser cannot represent."
        ) from exc


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LoadError("shape", "Each record must be an object with named fields.")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise LoadError("shape", "Record keys must be nonempty strings.")
        result[key] = item
    return result


def _json_records(text: str, options: LoadOptions) -> list[dict[str, object]]:
    value = _parse_json(text, options.max_depth)
    for key in options.records_path:
        container = _object(value)
        if key not in container:
            raise LoadError("shape", f"JSON records path component {key!r} is missing.")
        value = container[key]
    if not isinstance(value, list):
        raise LoadError(
            "shape",
            "Expected an array of objects. For a wrapper such as "
            '{"products": [...]}, set records_path=("products",).',
        )
    if len(value) > options.max_rows:
        raise LoadError("rows", "Dataset exceeds the row limit.")
    return [_object(item) for item in value]


def _jsonl_records(text: str, options: LoadOptions) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(_object(_parse_json(line, options.max_depth)))
        except LoadError as exc:
            raise LoadError(exc.code, f"JSONL line {number}: {exc}") from exc
        if len(records) > options.max_rows:
            raise LoadError("rows", "Dataset exceeds the row limit.")
    return records


def _xml_value(element: Element, depth: int, options: LoadOptions) -> object:
    if depth > options.max_depth:
        raise LoadError("depth", "XML exceeds the nesting limit.")
    children = list(element)
    if not children and not element.attrib:
        return element.text or ""
    result: dict[str, object] = {f"@{key}": val for key, val in element.attrib.items()}
    if children and (
        (element.text or "").strip()
        or any((child.tail or "").strip() for child in children)
    ):
        raise LoadError("shape", "Mixed XML text and child elements are not supported.")
    if not children and element.text is not None:
        result["#text"] = element.text
    grouped: dict[str, list[object]] = {}
    for child in children:
        grouped.setdefault(child.tag, []).append(_xml_value(child, depth + 1, options))
    for tag, values in grouped.items():
        result[tag] = values[0] if len(values) == 1 else values
    return result


def _xml_records(text: str, options: LoadOptions) -> list[dict[str, object]]:
    try:
        root = ElementTree.fromstring(
            text, forbid_dtd=True, forbid_entities=True, forbid_external=True
        )
    except (ParseError, DefusedXmlException) as exc:
        raise LoadError("xml", f"Invalid or prohibited XML: {exc}") from exc
    children = list(root)
    if (
        root.attrib
        or (root.text or "").strip()
        or any((child.tail or "").strip() for child in children)
    ):
        raise LoadError(
            "shape", "XML root must be a record container without metadata."
        )
    if options.xml_record_tag:
        if any(child.tag != options.xml_record_tag for child in children):
            raise LoadError(
                "shape", "XML has other root children; select records upstream."
            )
    elif len({child.tag for child in children}) > 1:
        raise LoadError("shape", "XML root children must have the same record tag.")
    if len(children) > options.max_rows:
        raise LoadError("rows", "Dataset exceeds the row limit.")
    return [_object(_xml_value(child, 1, options)) for child in children]


def _flatten(record: dict[str, object], options: LoadOptions) -> dict[str, object]:
    flat: dict[str, object] = {}

    def visit(value: object, prefix: str, depth: int) -> None:
        if depth > options.max_depth:
            raise LoadError("depth", "Record exceeds the nesting limit.")
        if isinstance(value, dict) and value:
            for key, item in _object(value).items():
                # Literal dots would collide with paths across different records.
                if "." in key:
                    raise LoadError("columns", "JSON/XML keys with dots are ambiguous.")
                visit(item, f"{prefix}.{key}" if prefix else key, depth + 1)
        else:
            flat[prefix] = value
            if len(flat) > options.max_columns:
                raise LoadError("columns", "Record exceeds the column limit.")

    visit(record, "", 0)
    if "" in flat:
        raise LoadError("shape", "Records must contain at least one named field.")
    return flat


def load_file_result(
    path: str | Path, options: LoadOptions | None = None
) -> ImportResult:
    """Read a bounded CSV, JSON, JSONL, or XML file into a raw DataFrame.

    Args:
        path: Local file path, supplied by trusted application code.
        options: Explicit parsing choices and resource limits.

    Returns:
        A table with source metadata and any parsing notices.

    Raises:
        LoadError: The file cannot be read or has an unsupported/invalid shape.
    """
    options = options or LoadOptions()
    _validate_options(options)
    path = Path(path)
    try:
        if not path.is_file():
            raise LoadError("file", "Input is missing or is not a regular file.")
        with path.open("rb") as source:
            raw = source.read(options.max_bytes + 1)
    except OSError as exc:
        raise LoadError(
            "file", "Cannot read input file; check access permissions."
        ) from exc
    if len(raw) > options.max_bytes:
        raise LoadError("size", f"Input exceeds the {options.max_bytes}-byte limit.")
    try:
        text = raw.decode(options.encoding)
    except (UnicodeError, LookupError) as exc:
        raise LoadError(
            "encoding", "Cannot decode file; set its actual encoding."
        ) from exc
    if not text.strip():
        raise LoadError("empty", "Input file is empty.")
    file_format = _detect(path, text, options)
    if options.records_path and file_format != "json":
        raise LoadError("options", "records_path applies only to JSON arrays.")
    if options.xml_record_tag and file_format != "xml":
        raise LoadError("options", "xml_record_tag applies only to XML.")
    if options.delimiter and file_format != "csv":
        raise LoadError("options", "delimiter applies only to CSV.")
    try:
        if file_format == "csv":
            records = _csv_records(text, path, options)
        elif file_format == "json":
            records = _json_records(text, options)
        elif file_format == "jsonl":
            records = _jsonl_records(text, options)
        else:
            records = _xml_records(text, options)
        if not records:
            raise LoadError("empty", "Dataset contains no records.")
        if file_format != "csv":
            records = [_flatten(record, options) for record in records]
        columns: set[str] = set()
        for record in records:
            columns.update(record)
            if len(columns) > options.max_columns:
                raise LoadError("columns", "Dataset exceeds the column limit.")
        warnings = []
        if any(set(record) != columns for record in records):
            warnings.append("Some fields are absent; missing cells are shown as null.")
        if any(
            isinstance(value, (dict, list)) for row in records for value in row.values()
        ):
            warnings.append(
                "Nested lists/empty objects are preserved in cells, not expanded."
            )
        # Fill only absent keys before pandas can introduce NaN. Never replace
        # submitted values (including empty strings, literal "NaN", or null).
        ordered_columns = list(dict.fromkeys(key for row in records for key in row))
        complete_records = [
            {key: row.get(key, None) for key in ordered_columns} for row in records
        ]
        # Object dtype preserves None, mixed types and large integer identifiers.
        frame = pd.DataFrame(complete_records, columns=ordered_columns, dtype=object)
        return ImportResult(frame, path.name, file_format, warnings)
    except RecursionError as exc:
        raise LoadError("depth", "Input nesting is too deep to parse.") from exc


def load_file(path: str | Path, options: LoadOptions | None = None) -> pd.DataFrame:
    """Return the parsed DataFrame without product-value validation.

    CSV/XML values remain strings. JSON scalar types are preserved, nested
    objects use dotted columns, and lists/empty objects remain cell values.
    No OFF schema, nutrient type, unit, range or barcode validation is performed.
    For metadata and previews use load_file_result instead.
    """
    return load_file_result(path, options).dataframe


def load_dataframe(
    frame: pd.DataFrame, options: LoadOptions | None = None
) -> pd.DataFrame:
    """Copy an existing DataFrame without validating or converting its values.

    Preserve columns, index, dtypes, missing values and nested cells. Pandas'
    deep copy does not recursively copy Python objects stored inside cells.
    Only option and resource-limit checks apply; file parsing options do not.
    """
    options = options or LoadOptions()
    _validate_options(options)
    if (
        options.format
        or options.delimiter
        or options.records_path
        or options.xml_record_tag
    ):
        raise LoadError("options", "File parsing options do not apply to DataFrames.")
    if len(frame) > options.max_rows:
        raise LoadError("rows", "Dataset exceeds the row limit.")
    if len(frame.columns) > options.max_columns:
        raise LoadError("columns", "Dataset exceeds the column limit.")
    return frame.copy(deep=True)
