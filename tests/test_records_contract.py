"""DataFrame handoff: preserve submitted values; validation belongs downstream."""

import json
from pathlib import Path

import pandas as pd
import pytest

from unknown_data import LoadError, LoadOptions, load_dataframe, load_file


@pytest.mark.parametrize(
    "suffix,content",
    [
        ("csv", "code,apple_suggar_100g\n00123,banana\n"),
        ("json", '[{"code":"00123","apple_suggar_100g":"banana"}]'),
        ("jsonl", '{"code":"00123","apple_suggar_100g":"banana"}\n'),
        (
            "xml",
            (
                "<products><product><code>00123</code>"
                "<apple_suggar_100g>banana</apple_suggar_100g></product></products>"
            ),
        ),
    ],
)
def test_accepts_arbitrary_product_values(
    tmp_path: Path, suffix: str, content: str
) -> None:
    path = tmp_path / f"products.{suffix}"
    path.write_text(content)
    frame = load_file(path)
    assert isinstance(frame, pd.DataFrame)
    assert frame.iloc[0]["apple_suggar_100g"] == "banana"
    assert frame.iloc[0]["code"] == "00123"


def test_retains_original_container_behavior(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps(
            [
                {
                    "nutrition": {"sugar": "banana"},
                    "tags": ["vegan"],
                    "empty_object": {},
                    "empty_list": [],
                    "value": None,
                }
            ]
        )
    )
    row = load_file(path).iloc[0]
    assert row["nutrition.sugar"] == "banana"
    assert row["tags"] == ["vegan"]
    assert row["empty_object"] == {}
    assert row["empty_list"] == []
    assert row["value"] is None


def test_dataframe_preserves_values_types_and_index() -> None:
    frame = pd.DataFrame(
        {
            "apple_suggar_100g": ["banana", -100],
            "nested": [{"a": [1, 2]}, {}],
            "missing": [pd.NA, float("nan")],
            "date": [pd.Timestamp("2026-01-01"), pd.NaT],
            "infinity": [float("inf"), float("-inf")],
        },
        index=["one", "two"],
        dtype=object,
    )
    output = load_dataframe(frame)
    assert output is not frame
    pd.testing.assert_frame_equal(output, frame)
    output.loc["one", "apple_suggar_100g"] = "changed"
    assert frame.loc["one", "apple_suggar_100g"] == "banana"


def test_dataframe_keeps_existing_columns_and_empty_frames() -> None:
    for frame in (
        pd.DataFrame(),
        pd.DataFrame([[1, 2]], columns=["a", "a"]),
        pd.DataFrame([["banana"]], columns=[123]),
    ):
        pd.testing.assert_frame_equal(load_dataframe(frame), frame)


def test_dataframe_retains_resource_limits() -> None:
    with pytest.raises(LoadError) as caught:
        load_dataframe(pd.DataFrame({"a": [1, 2]}), LoadOptions(max_rows=1))
    assert caught.value.code == "rows"


@pytest.mark.parametrize(
    "suffix,content",
    [
        ("csv", "a,b,c,d,e,f,g\nNaN,NA,null,,banana,00123,  text  \n"),
        (
            "json",
            (
                '[{"a":"NaN","b":"NA","c":"null","d":"",'
                '"e":"banana","f":"00123","g":"  text  "}]'
            ),
        ),
    ],
)
def test_preserves_missing_looking_strings(
    tmp_path: Path, suffix: str, content: str
) -> None:
    path = tmp_path / f"p.{suffix}"
    path.write_text(content)
    assert load_file(path).iloc[0].tolist() == [
        "NaN",
        "NA",
        "null",
        "",
        "banana",
        "00123",
        "  text  ",
    ]


@pytest.mark.parametrize(
    "suffix,content",
    [
        ("json", '[{"value":9007199254740993,"null":null},{"other":"banana"}]'),
        ("jsonl", '{"value":9007199254740993,"null":null}\n{"other":"banana"}\n'),
        (
            "xml",
            (
                "<rows><row><value>9007199254740993</value><null/>"
                "</row><row><other>banana</other></row></rows>"
            ),
        ),
    ],
)
def test_absent_fields_do_not_introduce_nan(
    tmp_path: Path, suffix: str, content: str
) -> None:
    path = tmp_path / f"p.{suffix}"
    path.write_text(content)
    frame = load_file(path)
    assert frame.iloc[0]["other"] is None
    assert frame.iloc[1]["value"] is None
    assert frame.iloc[1]["null"] is None
    assert (
        frame.iloc[0]["null"] == ""
        if suffix == "xml"
        else frame.iloc[0]["null"] is None
    )
    assert frame.iloc[0]["value"] == (
        "9007199254740993" if suffix == "xml" else 9007199254740993
    )
