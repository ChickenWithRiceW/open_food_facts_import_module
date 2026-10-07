#!/usr/bin/env python3
"""Local CSV -> OFF producer-upload CSV. Python 3.10+, standard library only."""

import argparse
import ast
import csv
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


# Explicit source nutrient IDs, never positions in an array.
USDA = {
    1003: "proteins", 1004: "fat", 1005: "carbohydrates",
    1008: "energy-kcal", 1062: "energy-kj", 2000: "sugars",
    1079: "fiber", 1087: "calcium", 1089: "iron", 1093: "sodium",
    1162: "vitamin-c", 1253: "cholesterol", 1258: "saturated-fat",
    1257: "trans-fat", 1092: "potassium", 1292: "monounsaturated-fat",
    1293: "polyunsaturated-fat", 1235: "added-sugars",
    1090: "magnesium", 1091: "phosphorus",
}
# Conservative subset: unknown codes are reported, not assigned to a nutrient.
SALSIFY = {
    "FAT": "fat", "FASAT": "saturated-fat", "CHOCDF": "carbohydrates",
    "CHOAVL": "carbohydrates", "SUGAR": "sugars", "PROCNT": "proteins",
    "FIBTG": "fiber", "SALTEQ": "salt", "NA": "sodium",
    "CA": "calcium", "FE": "iron", "K": "potassium",
}
UNITS = {"g": "g", "grm": "g", "mg": "mg", "mgm": "mg",
         "ug": "mcg", "µg": "mcg", "mcg": "mcg", "mc": "mcg",
         "kcal": "kcal", "kj": "kj", "ml": "ml", "mlt": "ml",
         "kg": "kg", "kgm": "kg", "l": "l", "ltr": "l"}
COUNTRIES = {"276": "en:germany", "DE": "en:germany",
             "040": "en:austria", "40": "en:austria", "AT": "en:austria"}


def unit(text):
    return UNITS.get(str(text).strip().lower())


def number(text):
    try:
        result = Decimal(str(text).strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"Not a numeric reference quantity: {text!r}") from exc
    if not result.is_finite():
        raise ValueError("Reference quantity must be finite")
    return result


def read_csv(path, delimiter=None):
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Trial converter accepts files up to 20 MiB")
    csv.field_size_limit(2 * 1024 * 1024)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(65536)
        stream.seek(0)
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.DictReader(stream, delimiter=delimiter, strict=True)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)) or any(not h for h in headers):
            raise ValueError("CSV requires unique nonempty headers")
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Unequal CSV row width near line {reader.line_num}")
            rows.append(row)
        if not rows:
            raise ValueError("CSV has no records")
        return headers, rows


def nutrient_list(text):
    if not text.strip():
        return []
    if len(text) > 1_000_000:
        raise ValueError("foodNutrients cell exceeds size limit")
    try:
        result = json.loads(text, parse_float=Decimal)
    except json.JSONDecodeError:
        # The existing loader writes Python list/dict representations to CSV.
        # literal_eval accepts literals only and never executes Python code.
        result = ast.literal_eval(text)
    if not isinstance(result, list) or any(not isinstance(x, dict) for x in result):
        raise ValueError("foodNutrients must contain a list of objects")
    return result


def convert(headers, rows, profile="auto", language=None):
    if profile == "auto":
        if {"gtinUpc", "foodNutrients"}.issubset(headers):
            profile = "usda"
        elif "GlobalTradeItemNumber" in headers or (
            "code" in headers and "nutritionalContent" in headers
        ):
            profile = "salsify"
        else:
            raise ValueError("Unrecognized CSV schema; expected USDA or Salsify columns")
    required = {"gtinUpc", "foodNutrients"} if profile == "usda" else {"nutritionalContent"}
    if not required.issubset(headers):
        raise ValueError(f"Missing required {profile} columns: {sorted(required-set(headers))}")
    language = language or ("en" if profile == "usda" else "de")
    if not re.fullmatch("[a-z]{2}", language):
        raise ValueError("Language must be a two-letter code, e.g. en or de")
    report = {"profile": profile, "language": language, "input_rows": len(rows),
              "issues": [], "skipped_source_rows": [], "used_source_columns": [],
              "note": "Offline conversion only; live OFF auto-selection not verified."}
    used = set()
    output = []
    seen = set()

    for row_index, row in enumerate(rows, 2):
        out = {}

        def get(*keys):
            for key in keys:
                if key in row:
                    used.add(key)
                    if row[key] != "":
                        return row[key]
            return ""

        def warn(message):
            report["issues"].append({"csv_row": row_index, "code": out.get("code", ""),
                                     "message": message})

        def add(name, value):
            if value is None or value == "":
                return
            value = str(value)
            if name in out and out[name] != value:
                raise ValueError(f"CSV row {row_index}: conflicting values for {name}")
            out[name] = value

        def nutrition(nid, value, source_unit, basis="100g"):
            u = unit(source_unit)
            allowed = {"energy-kcal": {"kcal"}, "energy-kj": {"kj"}}
            if u not in allowed.get(nid, {"g", "mg", "mcg"}):
                warn(f"Omitted {nid}: unsupported/unknown unit {source_unit!r}")
                return
            # These explicit-unit headers are generated by OFF's Producers.pm.
            # Energy's unit is part of the nutrient ID. Include it just once:
            # "energy_100g_kcal" matches the generated "Energy 100g kcal" alias.
            name = "energy" if nid.startswith("energy-") else nid
            add(f"{name}_{basis}_{u}", value)

        code = get("gtinUpc") if profile == "usda" else get("GlobalTradeItemNumber", "code")
        # Known Salsify template description rows, not product validation.
        if profile == "salsify" and (
            code in {"Muss", "GTIN der Artikeleinheit", "GDSN_GlobalTradeItemNumber[14 CHAR]"}
            or code.startswith(("Die Global Trade Item Number", "Teil des GDSN Primärschlüssels"))
        ):
            report["skipped_source_rows"].append({"csv_row": row_index, "reason": "template description", "value": code})
            continue
        if not code:
            raise ValueError(f"CSV row {row_index}: barcode missing; cannot identify product")
        add("code", code)
        if code in seen:
            raise ValueError(f"Duplicate barcode {code!r}; resolve duplicate product records first")
        seen.add(code)
        if not re.fullmatch(r"\d{8}|\d{12,14}", code):
            warn("Barcode format needs review; original text preserved")
        add("lc", language)

        if profile == "usda":
            add(f"product_name_{language}", get("description"))
            add(f"ingredients_text_{language}", get("ingredients"))
            add("brand_owner", get("brandOwner"))
            add("brands", get("brandName", "brand_name"))
            add("countries", get("marketCountry"))
            add("categories", get("brandedFoodCategory"))
            size, size_unit = get("servingSize"), get("servingSizeUnit")
            if size and unit(size_unit) in {"g", "ml"}:
                add("serving_size", f"{size} {unit(size_unit)}")
            # The supplied USDA Branded sample uses gram-based servings.
            # Do not infer a mass basis for other source datasets.
            if unit(size_unit) != "g":
                warn("Nutrition omitted: this USDA profile requires gram-based servings")
            else:
                for item in nutrient_list(get("foodNutrients")):
                    meta = item.get("nutrient", {})
                    if not isinstance(meta, dict):
                        raise ValueError(f"CSV row {row_index}: malformed nutrient metadata")
                    nid = USDA.get(meta.get("id"))
                    if not nid:
                        warn(f"Unmapped nutrient ID {meta.get('id')}: {meta.get('name')}; preserved in source only")
                        continue
                    nutrition(nid, item.get("amount"), meta.get("unitName", ""))
            # labelNutrients values are per serving. Never relabel as per 100 g.
        else:
            add(f"product_name_{language}", get("TIDDescriptionShort[de]", "short_description"))
            add(f"generic_name_{language}", get("regulatedProductNameValue[de]"))
            add(f"ingredients_text_{language}", get("ingredientStatementValue[de]", "ingredients"))
            add("brands", get("TIDBrandName", "brands"))
            add("brand_owner", get("NameOfBrandOwner", "brand_owner"))
            # Uppercase TargetMarketCountryCode is the GDSN target-market key.
            # The lowercase contact country field is not used.
            country = get("TargetMarketCountryCode")
            if country in COUNTRIES:
                add("countries", COUNTRIES[country])
            else:
                warn("Target market absent/unmapped; countries not guessed from text language")
            diet = get("wSCEDietTypeCode", "branded_food_category")
            if diet in {"VEGAN", "VEGETARIAN"}:
                add("labels", "en:" + diet.lower())
            elif diet:
                warn(f"Unmapped dietary code {diet!r}")
            for target, value_keys, unit_keys in [
                ("net_weight", ("NetWeight", "package_weight"), ("NetWeightUOM",)),
                ("serving_size", ("servingSizeValue", "serving_size"), ("servingSizeValueUOM", "serving_size_unit")),
            ]:
                value, u = get(*value_keys), get(*unit_keys)
                if value and unit(u) in {"g", "kg", "ml", "l"}:
                    add(target, f"{value} {unit(u)}")
                elif value:
                    warn(f"Omitted {target}: unknown unit {u!r}")
            ref, ref_unit = get("nutritionalValueReference"), get("nutritionalValueReferenceUOM")
            try:
                confirmed_100g = bool(ref) and number(ref) == 100 and unit(ref_unit) == "g"
            except ValueError:
                confirmed_100g = False
            if not confirmed_100g:
                warn("Nutrition omitted: reference is not confirmed 100 g; no rescaling or density assumed")
            else:
                add_energy = [("energy-kcal", ("calorificValueKcal", "foodNutrients.Energy.amount"), "kcal"),
                              ("energy-kj", ("calorificValueKJ", "foodNutrients.Energy.nutrient.unitName"), "kj")]
                for nid, keys, u in add_energy:
                    nutrition(nid, get(*keys), u)
                # Aliases produced by the current team's inverted mapping.
                aliases = {
                    "": "labelNutrients.fat.value", ".1": "foodNutrients.Fatty acids, total saturated.amount",
                    ".2": "foodNutrients.Sodium, Na.amount", ".3": "labelNutrients.carbohydrates.value",
                    ".4": "labelNutrients.fiber.value", ".5": "foodNutrients.Total Sugars.amount",
                    ".6": "foodNutrients.Protein.amount", ".7": "labelNutrients.calcium.value",
                    ".8": "labelNutrients.iron.value",
                }
                unit_aliases = {".1": "foodNutrients.Fatty acids, total saturated.nutrient.unitName",
                                ".2": "foodNutrients.Sodium, Na.nutrient.unitName",
                                ".5": "foodNutrients.Total Sugars.nutrient.unitName",
                                ".6": "foodNutrients.Protein.nutrient.unitName"}
                for key in headers:
                    if not re.fullmatch(r"nutritionalContent(?:\.\d+)?", key):
                        continue
                    suffix = key[len("nutritionalContent"):]
                    nutrient_code = get(key).strip()
                    value = get("nutritionalContentQuantityContainedValue" + suffix, aliases.get(suffix, ""))
                    u = get("nutritionalContentQuantityContainedUOM" + suffix, unit_aliases.get(suffix, ""))
                    if not nutrient_code and not value:
                        continue
                    nid = SALSIFY.get(nutrient_code.upper())
                    if nid is None:
                        warn(f"Unmapped nutrient code {nutrient_code!r} at {key}; no positional guess")
                        continue
                    nutrition(nid, value, u)
            if get("allergenTypeCode"):
                warn("Allergen codes not exported without presence/trace context and complete code mapping")
        output.append(out)

    if not output:
        raise ValueError("No product records remain")
    columns = list(dict.fromkeys(k for row in output for k in row))
    report.update(output_rows=len(output), output_columns=columns,
                  used_source_columns=sorted(used),
                  not_exported_source_columns=sorted(set(headers) - used))
    return columns, output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", choices=["auto", "usda", "salsify"], default="auto")
    parser.add_argument("--language", help="Text language: defaults en for USDA, de for Salsify")
    parser.add_argument("--delimiter", help="Input delimiter; autodetected by default")
    args = parser.parse_args()
    report_path = args.output.with_suffix(".report.json")
    try:
        if args.input.resolve() in {args.output.resolve(), report_path.resolve()}:
            raise ValueError("Output must differ from input")
        if args.output.exists() or report_path.exists():
            raise ValueError("Output/report already exists; choose a new output filename")
        headers, rows = read_csv(args.input, args.delimiter)
        columns, records, report = convert(headers, rows, args.profile, args.language)
        report["source_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Profile: {report['profile']}; products: {len(records)}; columns: {len(columns)}")
        print(f"CSV: {args.output}\nReview report: {report_path}")
        print(f"Review notices: {len(report['issues'])}; source rows excluded: {len(report['skipped_source_rows'])}")
    except (OSError, ValueError, csv.Error, SyntaxError, RecursionError) as exc:
        parser.exit(1, f"Conversion error: {exc}\n")


if __name__ == "__main__":
    main()
