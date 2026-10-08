import json
import warnings
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
import requests
from PIL import Image
from io import BytesIO
from functools import reduce

# Suppress openpyxl warnings about missing default styles
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


class ColumnNameConverter:
    """Convert and normalize data from Salsify/EDA to database schema using column_mapper.json"""

    GS1_NUTRIENT_CODES = {
        "FAT",
        "FASAT",
        "CHOAVL",
        "SUGAR-",
        "PRO-",
        "FIBTG",
        "SALTEQ",
        "FAMSCIS",
        "FAPUCIS",
    }

    def __init__(self, mapper_path: Optional[str] = None):
        """Initialize the converter with a column mapper file.

        Args:
            mapper_path: Path to column_mapper.json. If None, looks for it in the current directory.
        """
        if mapper_path is None:
            mapper_path = str(Path(__file__).parent / "column_mapper.json")

        self.mapper_path = Path(mapper_path)
        self.db_to_eda_map = self._load_mapper()
        self.eda_to_db_map = self._invert_mapper()

    def _load_mapper(self) -> Dict[str, Optional[str]]:
        """Load the column mapper from JSON file."""
        if not self.mapper_path.exists():
            raise FileNotFoundError(f"Column mapper file not found: {self.mapper_path}")

        with open(self.mapper_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _invert_mapper(self) -> Dict[Optional[str], str]:
        """Invert the mapper to go from EDA column names to database column names."""
        inverted: Dict[Optional[str], str] = {}
        for db_col, eda_col in self.db_to_eda_map.items():
            if eda_col is not None:
                inverted[eda_col] = db_col
        return inverted

    def _extract_gs1_nutrients(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """Dynamically extracts nutrients by scanning GS1 repeating group columns.

        In Salsify exports, nutrients are distributed across repeated columns
        ('nutritionalContent', 'nutritionalContent.1', etc.) instead of fixed indices.
        """
        slots = []
        for i in range(50):
            suffix = "" if i == 0 else f".{i}"
            code_col = f"nutritionalContent{suffix}"
            val_col = f"nutritionalContentQuantityContainedValue{suffix}"
            uom_col = f"nutritionalContentQuantityContainedUOM{suffix}"
            if code_col in df.columns and val_col in df.columns:
                slots.append(
                    (code_col, val_col, uom_col if uom_col in df.columns else None)
                )

        extracted: Dict[str, pd.Series] = {}
        for gs1_code in self.GS1_NUTRIENT_CODES:
            s_val = pd.Series(index=df.index, dtype="float64")
            for code_col, val_col, _ in slots:
                mask = df[code_col] == gs1_code
                if mask.any():
                    numeric_vals = pd.to_numeric(df.loc[mask, val_col], errors="coerce")
                    s_val = s_val.combine_first(numeric_vals)
            extracted[gs1_code] = s_val

        return extracted

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert DataFrame column names and extract nutrients into the database schema.

        Handles:
          1. Direct column mappings without dictionary inversion collisions.
          2. Dynamic GS1 nutrient extraction based on nutrient codes (PRO-, FAT, SALTEQ, etc.).
          3. Units and energy calculation (kcal / kJ).
        """
        result_df = pd.DataFrame(index=df.index)

        # Detect and extract dynamic GS1 nutrients if present
        has_gs1_nutrients = any("nutritionalContent" in col for col in df.columns)
        gs1_nutrients = self._extract_gs1_nutrients(df) if has_gs1_nutrients else {}

        for target_col, source in self.db_to_eda_map.items():
            if source is None:
                continue

            # Case A: Source is a GS1 nutrient code
            if source in self.GS1_NUTRIENT_CODES:
                if source in gs1_nutrients:
                    val_series = gs1_nutrients[source]
                    # Convert salt to sodium if target is sodium:
                    # 1 g salt (SALTEQ) = 0.4 g sodium (400 mg)
                    if "sodium" in target_col.lower() and source == "SALTEQ":
                        if "labelNutrients" in target_col or "mg" in target_col.lower():
                            result_df[target_col] = val_series * 400.0
                        else:
                            result_df[target_col] = val_series / 2.5
                    else:
                        result_df[target_col] = val_series

            # Case B: Source is a direct column present in input DataFrame
            elif source in df.columns:
                val_series = df[source].copy()
                # Combine any repeating column variants (e.g. source.1, source.2, etc.)
                for i in range(1, 10):
                    col_variant = f"{source}.{i}"
                    if col_variant in df.columns:
                        val_series = val_series.combine_first(df[col_variant])

                # Transform specific fields if needed
                if target_col == "market_country":
                    # Convert ISO numeric country code (276 -> Germany)
                    country_map = {
                        "276": "Germany",
                        276: "Germany",
                        "DE": "Germany",
                        "de": "Germany",
                    }
                    val_series = val_series.map(
                        lambda x: (
                            country_map.get(str(x).strip(), x) if pd.notna(x) else x
                        )
                    )

                result_df[target_col] = val_series

            # Case C: Source is a static unit or metadata string
            elif source in ["g", "kcal", "kJ", "mg", "GRM", "MLT", "de", "GDSN"]:
                result_df[target_col] = source

        # Populate flat nutrient columns if present in target schema or needed
        if "fat_value" not in result_df.columns and "FAT" in gs1_nutrients:
            result_df["fat_value"] = gs1_nutrients["FAT"]
            result_df["fat_unit"] = "g"
        if "saturated_fat_value" not in result_df.columns and "FASAT" in gs1_nutrients:
            result_df["saturated_fat_value"] = gs1_nutrients["FASAT"]
            result_df["saturated_fat_unit"] = "g"
        if "carbohydrates_value" not in result_df.columns and "CHOAVL" in gs1_nutrients:
            result_df["carbohydrates_value"] = gs1_nutrients["CHOAVL"]
            result_df["carbohydrates_unit"] = "g"
        if "sugar_value" not in result_df.columns and "SUGAR-" in gs1_nutrients:
            result_df["sugar_value"] = gs1_nutrients["SUGAR-"]
            result_df["sugar_unit"] = "g"
        if "fiber_value" not in result_df.columns and "FIBTG" in gs1_nutrients:
            result_df["fiber_value"] = gs1_nutrients["FIBTG"]
            result_df["fiber_unit"] = "g"
        if "protein_value" not in result_df.columns and "PRO-" in gs1_nutrients:
            result_df["protein_value"] = gs1_nutrients["PRO-"]
            result_df["protein_unit"] = "g"
        if "salt_value" not in result_df.columns and "SALTEQ" in gs1_nutrients:
            result_df["salt_value"] = gs1_nutrients["SALTEQ"]
            result_df["salt_unit"] = "g"
        if (
            "energy_value" not in result_df.columns
            and "calorificValueKcal" in df.columns
        ):
            result_df["energy_value"] = pd.to_numeric(
                df["calorificValueKcal"], errors="coerce"
            )
            result_df["energy_unit"] = "kcal"
        if (
            "energy_kj_value" not in result_df.columns
            and "calorificValueKJ" in df.columns
        ):
            result_df["energy_kj_value"] = pd.to_numeric(
                df["calorificValueKJ"], errors="coerce"
            )
            result_df["energy_kj_unit"] = "kJ"

        return result_df

    def save_converted_data(self, converted_df: pd.DataFrame, output_path: str) -> None:
        """Convert DataFrame and save to file.

        Args:
            converted_df: DataFrame with converted column names
            output_path: Path to save the converted data
        """
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        converted_df.to_csv(out_path, index=False, encoding="utf-8")

        print(f"Converted data saved to: {out_path}")

    def download_product_images(
        self,
        df: pd.DataFrame,
        output_dir: str = "product_images",
        code_column: str = "code",
        url_column: str = "product_front_image_link",
    ) -> dict:
        """Download product images from URLs and save as JPG files named by product code.

        Args:
            df: DataFrame containing product codes and image URLs
            output_dir: Directory to save images (relative or absolute path)
            code_column: Name of column containing product codes
            url_column: Name of column containing image URLs

        Returns:
            dict with keys 'successful', 'failed', 'failed_codes', 'output_dir'
        """
        images_path = Path(output_dir)
        images_path.mkdir(parents=True, exist_ok=True)

        successful = 0
        failed = 0
        failed_codes = []

        for idx, row in df.iterrows():
            code = str(row[code_column]).strip()
            image_url = str(row[url_column]).strip()

            # Skip if URL is empty or NaN
            if not image_url or image_url.lower() == "nan":
                continue

            try:
                # Download image
                response = requests.get(image_url, timeout=10)
                response.raise_for_status()

                # Convert to JPG and save
                img = Image.open(BytesIO(response.content)).convert("RGB")
                image_path = images_path / f"{code}.jpg"
                img.save(image_path, "JPEG", quality=95)

                successful += 1
                if (idx + 1) % 50 == 0:
                    print(f"Downloaded {idx + 1} images...")

            except Exception as e:
                failed += 1
                failed_codes.append(code)
                if failed <= 10:  # Show first 10 errors
                    print(f"Failed to download {code}: {str(e)[:100]}")

        result = {
            "successful": successful,
            "failed": failed,
            "failed_codes": failed_codes,
            "output_dir": str(images_path.resolve()),
        }

        print(f"\n✓ Successfully downloaded: {successful}")
        print(f"✗ Failed: {failed}")
        print(f"Images saved to: {result['output_dir']}")

        return result

    def merge_sheets(self, excel_file: str) -> pd.DataFrame:
        all_sheets = {
            sheet_name: pd.read_excel(excel_file, sheet_name=sheet_name, header=5).iloc[5:]
            for sheet_name in pd.ExcelFile(excel_file).sheet_names
        }


        def clean_sheet_name(sheet_name: str) -> str:
            return (
                sheet_name.split(" - ", 1)[1]
                .replace(", ", "_")
                .replace("  ", " ")
                .replace(" ", "_")
                .replace("&", "")
                .replace("__", "_")
                if " - " in sheet_name
                else sheet_name
            )

        df = {clean_sheet_name(name): s_df for name, s_df in all_sheets.items()}

        nutri_cols = [
            "GlobalTradeItemNumber",
            "ingredientStatementValue[de]",
            "FBSNumberOfServingsPerPackage",
            "wSCEDietTypeCode",
            "allergenTypeCode",
            "nutritionalValueReference",
            "nutritionalValueReferenceUOM",
            "servingSizeValue",
            "servingSizeValueUOM",
            "calorificValueKcal",
            "calorificValueKJ",
        ]
        # Include all nutritionalContent, servingSize, and preparationState slots present in sheet
        for col in df["Angaben_für_die_Lebensmitt"].columns:
            if (
                col.startswith("nutritionalContent")
                or col.startswith("servingSize")
                or col.startswith("preparationState")
            ) and col not in nutri_cols:
                nutri_cols.append(col)

        dfs_to_merge = [
            df["Angaben_für_die_Gesundheit"][
                ["GlobalTradeItemNumber", "HRICompulsoryAdditivesLabelInformation[de]"]
            ],
            df["Gefahrgut_Gefahrstoff"][
                ["GlobalTradeItemNumber", "WSCEDangerousGoodsIndication"]
            ],
            df["Artikellogistik"][["GlobalTradeItemNumber", "link"]],
            df["Angaben_für_die_Lebensmitt"][nutri_cols],
            df["Artikelverpackung"][
                ["GlobalTradeItemNumber", "IsPackagingMarkedReturnable"]
            ],
            df["Artikelmaße"][
                [
                    "GlobalTradeItemNumber",
                    "NetWeight",
                    "NetWeightUOM",
                    "GrossWeightValue",
                    "GrossWeightUOM",
                ]
            ],
            df["Artikelbeschreibung"][
                [
                    "GlobalTradeItemNumber",
                    "TIDBrandName",
                    "TIDSubBrand",
                    "TIDFunctionalName[de]",
                    "TIDDescriptionShort[de]",
                    "regulatedProductNameValue[de]",
                ]
            ],
            df["Artikelidentifikation"][
                [
                    "GlobalTradeItemNumber",
                    "NameOfBrandOwner",
                    "TargetMarketCountryCode",
                    "EffectiveDateTime",
                    "PublicationDateTime",
                    "DiscontinuedDate",
                    "tradeItemtradeChannel",
                ]
            ],
        ]

        merged_df = reduce(
            lambda left, right: left.merge(
                right, on="GlobalTradeItemNumber", how="outer"
            ),
            dfs_to_merge,
        )

        return merged_df


# Example usage
if __name__ == "__main__":

    default_input = (
        Path(__file__).parent.parent / "dev_data_struct" / "sample_salsify.xlsx"
    )
    excel_file = (
        default_input
        if default_input.exists()
        else Path(__file__).parent.parent / "input" / "sample_salsify.xlsx"
    )

    output_path = Path(__file__).parent.parent / "loader_output.csv"

    try:
        converter = ColumnNameConverter()
        merged_df = converter.merge_sheets(excel_file)
        converted_df = converter.convert(merged_df)
        converter.save_converted_data(converted_df, str(output_path))
        converter.download_product_images(converted_df)

    except FileNotFoundError as e:
        print(f"Error: {e}")
