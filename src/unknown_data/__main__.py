"""Small command-line demonstration; no web server or external writes."""

import argparse
import json
import sys
from typing import cast

from unknown_data.loader import Format, LoadError, LoadOptions, load_file


def main() -> int:
    """Print a JSON preview, or a structured error with a nonzero exit code."""
    parser = argparse.ArgumentParser(description="Load a raw product dataset.")
    parser.add_argument("file")
    parser.add_argument("--format", choices=["csv", "json", "jsonl", "xml"])
    parser.add_argument("--encoding", default="utf-8-sig")
    parser.add_argument("--delimiter")
    parser.add_argument("--records-key", action="append", default=[])
    parser.add_argument("--xml-record-tag")
    args = parser.parse_args()
    options = LoadOptions(
        format=cast(Format | None, args.format),
        encoding=args.encoding,
        delimiter=args.delimiter,
        records_path=tuple(args.records_key),
        xml_record_tag=args.xml_record_tag,
    )
    try:
        result = load_file(args.file, options)
    except LoadError as exc:
        print(
            json.dumps({"error": {"code": exc.code, "message": str(exc)}}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result.preview(), ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
