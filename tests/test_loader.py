"""Behavioral tests for the raw ingestion boundary."""

import json
from pathlib import Path

import pandas as pd
import pytest

from unknown_data import LoadError, LoadOptions, load_file


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadFile:
    """Preserve source values and reject invalid files without partial success."""

    def test_limits_nesting_inside_preserved_lists(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.json", '[{"tags":[[[["x"]]]]}]')
        with pytest.raises(LoadError) as caught:
            load_file(path, LoadOptions(max_depth=3))
        assert caught.value.code == "depth"

    def test_rejects_integer_larger_than_parser_limit(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.json", '[{"value":' + "9" * 5000 + "}]")
        with pytest.raises(LoadError) as caught:
            load_file(path)
        assert caught.value.code == "json"

    def test_preserves_csv_identifiers_literals_and_quoted_fields(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path, "p.csv", 'code,name,note\n00123,"Juice, apple",NA\n00999,Water,\n'
        )
        frame = load_file(path).dataframe
        assert frame.iloc[0].to_dict() == {
            "code": "00123",
            "name": "Juice, apple",
            "note": "NA",
        }
        assert frame.iloc[1]["note"] == ""

    @pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
    def test_detects_delimiters(self, tmp_path: Path, delimiter: str) -> None:
        path = write(tmp_path, "p.csv", f"code{delimiter}name\n001{delimiter}Juice\n")
        assert load_file(path).dataframe.iloc[0]["code"] == "001"

    def test_handles_multiline_quoted_csv(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.csv", 'code,name\n001,"Apple\njuice"\n')
        assert load_file(path).dataframe.iloc[0]["name"] == "Apple\njuice"

    @pytest.mark.parametrize("row", ["001", "001,Juice,Extra", '001,"unclosed'])
    def test_rejects_bad_csv_rows(self, tmp_path: Path, row: str) -> None:
        with pytest.raises(LoadError):
            load_file(write(tmp_path, "p.csv", f"code,name\n{row}\n"))

    @pytest.mark.parametrize("header", ["code,code", "code,", " ,name"])
    def test_rejects_ambiguous_csv_headers(self, tmp_path: Path, header: str) -> None:
        with pytest.raises(LoadError, match="column"):
            load_file(write(tmp_path, "p.csv", f"{header}\n001,Juice\n"))

    def test_json_wrapper_flattening_missing_values_and_lists(
        self, tmp_path: Path
    ) -> None:
        content = {
            "data": {
                "products": [
                    {"code": "001", "nutrition": {"sugar": 3.4}, "tags": ["vegan"]},
                    {"code": "002"},
                ]
            }
        }
        result = load_file(
            write(tmp_path, "p.json", json.dumps(content)),
            LoadOptions(records_path=("data", "products")),
        )
        assert result.dataframe.iloc[0]["nutrition.sugar"] == 3.4
        assert result.dataframe.iloc[0]["tags"] == ["vegan"]
        assert pd.isna(result.dataframe.iloc[1]["nutrition.sugar"])
        assert len(result.warnings) == 2
        assert result.preview()["preview"] == [
            {"code": "001", "nutrition.sugar": 3.4, "tags": ["vegan"]},
            {"code": "002", "nutrition.sugar": None, "tags": None},
        ]

    def test_json_preserves_large_integer_with_missing_value(
        self, tmp_path: Path
    ) -> None:
        path = write(tmp_path, "p.json", '[{"code":9007199254740993},{"name":"juice"}]')
        assert load_file(path).dataframe.iloc[0]["code"] == 9007199254740993

    @pytest.mark.parametrize(
        "content",
        [
            "[{",
            '[{"code":1,"code":2}]',
            '[{"x":NaN}]',
            '[{"x":Infinity}]',
            '[{"x":1e400}]',
            "[1,2]",
            '{"products":[]}',
            "[{}]",
            '[{"a.b":1},{"a":{"b":2}}]',
        ],
    )
    def test_rejects_invalid_or_ambiguous_json(
        self, tmp_path: Path, content: str
    ) -> None:
        with pytest.raises(LoadError):
            load_file(write(tmp_path, "p.json", content))

    def test_jsonl_reports_original_line_number(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.jsonl", '{"code":"001"}\n\n{broken}\n')
        with pytest.raises(LoadError, match="JSONL line 3"):
            load_file(path)

    def test_reads_jsonl(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.ndjson", '{"code":"001"}\n{"code":"002"}\n')
        assert list(load_file(path).dataframe["code"]) == ["001", "002"]

    def test_reads_xml_nested_attributes_and_repeated_fields(
        self, tmp_path: Path
    ) -> None:
        path = write(
            tmp_path,
            "p.xml",
            '<products><product id="001"><name>Juice</name>'
            "<nutrition><sugar>3.4</sugar></nutrition><tag>a</tag><tag>b</tag>"
            "</product></products>",
        )
        row = load_file(path).dataframe.iloc[0]
        assert row["@id"] == "001"
        assert row["nutrition.sugar"] == "3.4"
        assert row["tag"] == ["a", "b"]

    @pytest.mark.parametrize(
        "content",
        [
            "<products><product></products>",
            '<!DOCTYPE x [<!ENTITY x "hello">]><p><r><name>&x;</name></r></p>',
            "<p><product><name>Juice</name></product><metadata>Other</metadata></p>",
            "<p><r><name>hello<b>bold</b>world</name></r></p>",
            '<p version="1"><r><name>Juice</name></r></p>',
        ],
    )
    def test_rejects_invalid_or_unsupported_xml(
        self, tmp_path: Path, content: str
    ) -> None:
        with pytest.raises(LoadError):
            load_file(write(tmp_path, "p.xml", content))

    @pytest.mark.parametrize(
        "name,content",
        [
            ("p.csv", ""),
            ("p.csv", "code\n"),
            ("p.json", "[]"),
            ("p.xml", "<products/>"),
        ],
    )
    def test_rejects_empty_input(self, tmp_path: Path, name: str, content: str) -> None:
        with pytest.raises(LoadError) as caught:
            load_file(write(tmp_path, name, content))
        assert caught.value.code == "empty"

    def test_checks_missing_file_and_directory(self, tmp_path: Path) -> None:
        for path in (tmp_path / "missing.csv", tmp_path):
            with pytest.raises(LoadError) as caught:
                load_file(path)
            assert caught.value.code == "file"

    def test_encoding_is_explicit(self, tmp_path: Path) -> None:
        path = tmp_path / "p.csv"
        path.write_bytes("code,name\n001,café\n".encode("cp1252"))
        with pytest.raises(LoadError) as caught:
            load_file(path)
        assert caught.value.code == "encoding"
        assert (
            load_file(path, LoadOptions(encoding="cp1252")).dataframe.iloc[0]["name"]
            == "café"
        )

    def test_utf8_bom(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.csv", "\ufeffcode,name\n001,Juice\n")
        assert "code" in load_file(path).dataframe.columns

    @pytest.mark.parametrize(
        "options,code",
        [
            (LoadOptions(max_bytes=2), "size"),
            (LoadOptions(max_rows=1), "rows"),
            (LoadOptions(max_columns=1), "columns"),
            (LoadOptions(max_depth=1), "depth"),
            (LoadOptions(max_rows=0), "options"),
        ],
    )
    def test_enforces_limits(
        self, tmp_path: Path, options: LoadOptions, code: str
    ) -> None:
        path = write(tmp_path, "p.json", '[{"code":"001","n":{"v":1}},{"code":"002"}]')
        with pytest.raises(LoadError) as caught:
            load_file(path, options)
        assert caught.value.code == code

    def test_explicit_format_for_unknown_extension(self, tmp_path: Path) -> None:
        path = write(tmp_path, "p.data", "code,name\n001,Juice\n")
        with pytest.raises(LoadError) as caught:
            load_file(path)
        assert caught.value.code == "format"
        assert load_file(path, LoadOptions(format="csv")).format == "csv"

    def test_content_detection_for_json(self, tmp_path: Path) -> None:
        assert load_file(write(tmp_path, "p.data", '[{"code":"001"}]')).format == "json"
