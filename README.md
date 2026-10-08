# Salsify Product Import for Open Food Facts

Prepare German Salsify product data for import into [Open Food Facts](https://world.openfoodfacts.org/).

Developed during the Forty2 hackathon, this program reads the supplied Excel workbook, joins product information, maps fields and nutrients, and downloads associated product images. The resulting CSV and photos can then be imported through the OFF producer platform.

## 1. Install and run

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and an internet connection for image downloads.

```bash
git clone --branch salsify https://github.com/ChickenWithRiceW/open_food_facts_import_module.git
cd open_food_facts_import_module
uv sync
uv run --with openpyxl --with requests --with pillow python src/pipeline/plugin.py
```

Run the command from the repository root. The program uses these paths:

| File or directory | Purpose |
| --- | --- |
| `src/input/sample_salsify.xlsx` | Input workbook |
| `src/pipeline/column_mapper.json` | Source-to-target mapping rules |
| **`src/loader_output.csv`** | Generated CSV: UTF-8, comma-separated, no index |
| **`product_images/`** | Downloaded JPEGs, named `<code>.jpg` |

Running the script again replaces the CSV and any downloaded images with the same filenames. The program does not upload anything to OFF.

## 2. Import the CSV into OFF

Use the [Open Food Facts producer platform](https://world.pro.openfoodfacts.org/) with the organisation account agreed with the team.

1. Open the product-data import page and select **`src/loader_output.csv`**.
2. Review the proposed column matches. Complete or correct them using the table below.
3. Import the data into the producer workspace, then inspect the resulting product records.

Column recognition is a starting point; the current CSV still needs mapping review. The [format-selection page](https://world.pro.openfoodfacts.org/cgi/import_file_select_format.pl) belongs to an uploaded-file session, so start with file upload rather than opening that URL on its own.

### Column mapping for this CSV

| CSV column | OFF field to select | What to check |
| --- | --- | --- |
| `code` | Barcode | Keep the full identifier, including leading zeros |
| `product_name` | Product name | German text |
| `brands` | Brands | Brand names |
| `brand_owner` | Brand owner | Organisation name |
| `ingredients` | Ingredients text | German text |
| `market_country` | Countries where sold | Sales market, not ingredient origin |
| `branded_food_category` | Categories | Match the source category to an appropriate OFF category |
| `fat_value` | Fat | Check `fat_unit` and nutrition basis |
| `saturated_fat_value` | Saturated fat | Check `saturated_fat_unit` and nutrition basis |
| `carbohydrates_value` | Carbohydrates | Check `carbohydrates_unit` and nutrition basis |
| `sugar_value` | Sugars | Check `sugar_unit` and nutrition basis |
| `fiber_value` | Fiber | Check `fiber_unit` and nutrition basis |
| `protein_value` | Proteins | Check `protein_unit` and nutrition basis |
| `salt_value` | Salt | Check `salt_unit`; do not relabel it as sodium |
| `energy_value` | Energy in kcal | Check nutrition basis |
| `energy_kj_value` | Energy in kJ | Check nutrition basis |

Set the appropriate language and nutrient-unit options on the mapping screen. Use the `*_unit` columns as references when selecting units; they are not additional nutrient amounts.

**Check the nutrition basis in the original workbook.** The reader selects `nutritionalValueReference` and `nutritionalValueReferenceUOM`, but the mapper does not include them in the final CSV. Do not assume every value is per 100 g, per 100 ml or per serving. Also check `preparation_state_code` before mapping prepared-product nutrition. Leave uncertain fields unmapped until resolved.

The CSV contains repeated representations of nutrition in `labelNutrients.*`, `foodNutrients.*` and the flat `*_value` columns. Map one verified representation of each nutrient, not all copies. Likewise, `short_description` duplicates the source used for `product_name`.

For package weight and serving size, verify the corresponding units in the workbook before importing them. `package_weight` alone does not include its source unit in the output. Leave technical or unverified columns unmapped instead of assigning them to unrelated OFF fields.


## 3. Import product photos

The script saves local files such as `product_images/00000040045009.jpg`. Downloading them does not attach them to an OFF product.

OFF supports public image URLs in the data import, or a separate **Import product photos** upload. Agree with the team which route to use.

- **URLs:** `product_front_image_link` contains the source link. Verify that it is publicly accessible and actually shows the product front before mapping it as a front image.
- **Local files:** the OFF guide recommends filenames in the form `<barcode>_<image-type>_<language>.jpg`, for example `00000040045009_front_de.jpg`. The script currently saves only `<code>.jpg`; it does not add image type or language. Confirm those details before preparing the upload filenames.


## 4. Review and publish

Check imported products in the producer workspace, correct errors and complete missing information. Then use the platform's export-to-public-database step. The official guide describes an OFF review for a first export.

For this dataset, compare a small sample against the original workbook: barcode, German product name, ingredients, nutrient values and units, reference quantity, and image association. After publication, verify the corresponding public product pages.

Keep the original workbook, generated CSV, mapping choices and import outcome together so another team member can repeat the process.

## Project files

| Path | Role |
| --- | --- |
| `src/pipeline/plugin.py` | Workbook processing, mapping, CSV writing and image downloading |
| `src/pipeline/column_mapper.json` | Target fields associated with source columns, nutrient codes or supported constants |
| `src/pipeline/eda.ipynb` | Exploratory analysis notebook |
| `src/dev_data_struct/sample_salsify.xlsx` | Workbook used by the script by default |
| `src/input/sample_salsify.xlsx` | Fallback copy of the input workbook |
| `src/loader_output.csv` | CSV generated by the script |

`src/findings.csv` and `src/test_img.csv` are also present on the branch, but the script's main entry point does not generate or use them.
