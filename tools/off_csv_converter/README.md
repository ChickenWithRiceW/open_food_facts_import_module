# Open Food Facts CSV converter — trial

This standalone program prepares a CSV for the OFF producer upload screen.
Requires Python 3.10+ only. No pip, pandas, API key, or Git changes are needed.
It does not upload data or publish products.

## Try the supplied file

The uploaded `loader_output.csv` contains **22 US FoodData Central products**,
not the German Salsify dataset. The program detects this from the columns.
`off_import_trial.csv` is its converted output (22 products, 27 columns).
`off_import_trial.report.json` explains omissions and includes the input hash.

1. Extract this ZIP.
2. Upload `off_import_trial.csv` on the OFF producers platform.
3. On the mapping screen check barcode, English product name/ingredients,
   nutrient names, per-100-g basis, and units before confirming anything.
4. For the first granola record expect sugars **21.4 g per 100 g**, sodium
   **161 mg per 100 g**, and energy **500 kcal per 100 g**.
   The original label value 5.99 g sugars is per 28 g serving and is NOT used
   as the per-100-g value.

The program has been tested locally, but not in your signed-in OFF account.
Matching depends on the deployed OFF version and previously saved mappings for
your organization. A CSV can preselect mappings; it cannot skip upload confirmation.
Names/categories may be recognized as fields without every category value matching
an OFF taxonomy entry. Nutrient meaning is preserved from the source; no missing
values or product facts are invented.

## Convert another file

From this extracted folder:

```bash
python3 convert_off.py /path/to/loader_output.csv my_off_import.csv
```

Outputs: `my_off_import.csv` and `my_off_import.report.json`.
Choose a new filename for a new run; existing files are not overwritten.
Input is read as UTF-8, with optional BOM. Delimiter is detected; override with
`--delimiter ';'` if needed. Output is UTF-8 comma-separated CSV, without an index.

## German Salsify trial mode

```bash
python3 convert_off.py /path/to/german_loader_output.csv german_off_import.csv --profile salsify
```

This adapter supports the raw merged Salsify columns and the renamings in the
team's current `salsify/src/pipeline/column_mapper.json`. It does not read XLSX.
It is tested on synthetic German records only: no actual German CSV was supplied.

- Keep `nutritionalContent`, `nutritionalContent.1`, etc. They identify nutrients.
- Keep matching values and units plus `nutritionalValueReference` and its UOM.
- Supported nutrient identifiers are explicitly listed in `SALSIFY` in the script.
- Unknown nutrient codes/units are reported and omitted, not guessed from position.
- Only a confirmed reference of 100 GRM/g is exported as per 100 g in this trial.
  Other bases, liquids and prepared-product nutrition require a further adapter.
- Known spreadsheet-description rows (e.g. `Muss`) are excluded and reported.
- GTINs remain strings. Duplicate or missing product identities stop conversion.
- German text is exported with `_de`; `TargetMarketCountryCode` identifies markets.
  The different lowercase contact-country field is intentionally not used.
- Allergen codes are reported but not exported: the current source lacks verified
  presence-versus-traces context. Images are also omitted without a verified type.
- The original input retains all omitted information. The report lists unused
  source columns and row-specific mapping issues. Keep it with your source file.

## USDA profile and value preservation

The actual supplied sample has gram-based serving units. USDA `foodNutrients`
contains the standardized per-100-g values; the separate `labelNutrients.*` values
are not used. Non-gram USDA records produce a report notice and omit nutrition.

Supported nutrients are mapped by stable USDA nutrient ID, not array position.
Sodium remains sodium; it is not silently relabeled as salt. Micronutrient units
stay mg/mcg when supplied. Vitamins A/D in IU are omitted in this trial to avoid
unverified biological-unit conversions: the supplied output report has 19 notices
for these omitted values. Zero values for these unsupported nutrients are also
reported. Other source columns such as update logs remain only in the input.

CSV strings (including barcode zeroes, ingredients, whitespace, literal `NA` and
`NaN`) are read unchanged. Numeric values inside the serialized nutrient objects
are parsed; original numeric spelling/trailing zero formatting is not guaranteed.
No product-value range or nutrition plausibility rules are applied. Consequently
invalid source values can still fail OFF's own import checks. Empty output cells
mean no exported value, never a fabricated zero or the string `None`.

## Checks

```bash
python3 -m unittest -v test_converter.py
```

15 tests cover identifiers, nutrient meaning/basis, unit handling, preserved text,
German code-based mapping, template rows, duplicate identities and parsing errors.

## Why these output headers?

OFF's `init_nutrients_columns_names_for_lang` generates aliases from nutrient
names, basis and unit, for example `sugars_100g_g` and `energy_100g_kcal`.
`add_language_field_column_names` and `match_column_name_to_field` support language
suffixes such as `product_name_de` and `ingredients_text_en`.

Sources inspected on 2026-10-07:
- https://github.com/openfoodfacts/openfoodfacts-server/blob/main/lib/ProductOpener/Producers.pm
- https://github.com/openfoodfacts/openfoodfacts-server/blob/main/tests/unit/producers.t
- https://github.com/openfoodfacts/openfoodfacts-server/blob/main/taxonomies/nutrients.txt
- https://fdc.nal.usda.gov/GBFPD_Documentation/
- https://github.com/ChickenWithRiceW/open_food_facts_import_module/blob/salsify/src/pipeline/column_mapper.json

This adapter is separate from the team's loader. Its functions can be imported
later; for the first trial, run it as a standalone script and review the output.
