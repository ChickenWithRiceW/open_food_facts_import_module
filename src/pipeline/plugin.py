import json
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd


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
                result_df[target_col] = df[source]

            # Case C: Source is a static unit string
            elif source in ["g", "kcal", "kJ", "mg", "GRM", "MLT"]:
                result_df[target_col] = source

        # Populate flat nutrient columns if present in target schema or needed
        if "protein_value" not in result_df.columns and "PRO-" in gs1_nutrients:
            result_df["protein_value"] = gs1_nutrients["PRO-"]
            result_df["protein_unit"] = "g"
        if "sugar_value" not in result_df.columns and "SUGAR-" in gs1_nutrients:
            result_df["sugar_value"] = gs1_nutrients["SUGAR-"]
            result_df["sugar_unit"] = "g"
        if "salt_value" not in result_df.columns and "SALTEQ" in gs1_nutrients:
            result_df["salt_value"] = gs1_nutrients["SALTEQ"]
            result_df["salt_unit"] = "g"
        if "saturated_fat_value" not in result_df.columns and "FASAT" in gs1_nutrients:
            result_df["saturated_fat_value"] = gs1_nutrients["FASAT"]
            result_df["saturated_fat_unit"] = "g"
        if (
            "energy_value" not in result_df.columns
            and "calorificValueKcal" in df.columns
        ):
            result_df["energy_value"] = pd.to_numeric(
                df["calorificValueKcal"], errors="coerce"
            )
            result_df["energy_unit"] = "kcal"

        return result_df

    def get_unmapped_columns(self, df: pd.DataFrame) -> List[str]:
        """Get list of columns in DataFrame that don't have a mapping.

        Args:
            df: DataFrame to check

        Returns:
            List of unmapped column names
        """
        mapped_sources = set(self.db_to_eda_map.values())
        return [
            col
            for col in df.columns
            if col not in mapped_sources and not col.startswith("nutritionalContent")
        ]

    def get_mapping_info(self) -> Dict[str, object]:
        """Get information about the mappings.

        Returns:
            Dictionary with mapping statistics
        """
        total_db_columns = len(self.db_to_eda_map)
        mapped_db_columns = sum(1 for v in self.db_to_eda_map.values() if v is not None)
        unmapped_db_columns = total_db_columns - mapped_db_columns

        return {
            "total_db_columns": total_db_columns,
            "mapped_db_columns": mapped_db_columns,
            "unmapped_db_columns": unmapped_db_columns,
            "db_to_eda_map": self.db_to_eda_map,
        }

    def save_converted_data(
        self, df: pd.DataFrame, output_path: str, format: str = "csv"
    ) -> None:
        """Convert DataFrame and save to file.

        Args:
            df: DataFrame with EDA column names
            output_path: Path to save the converted data
            format: File format ('csv', 'excel', 'tsv', or 'parquet')
        """
        converted_df = self.convert(df)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        fmt = format.lower()
        if fmt == "csv":
            converted_df.to_csv(out_path, index=False, encoding="utf-8")
        elif fmt == "tsv":
            converted_df.to_csv(out_path, index=False, sep="\t", encoding="utf-8")
        elif fmt in ["excel", "xlsx"]:
            converted_df.to_excel(out_path, index=False)
        elif fmt == "parquet":
            converted_df.to_parquet(out_path, index=False)
        else:
            raise ValueError(
                f"Unsupported format: {format}. Use 'csv', 'tsv', 'excel', or 'parquet'."
            )

        print(f"Converted data saved to: {out_path}")


# Example usage
if __name__ == "__main__":
    from functools import reduce

    converter = ColumnNameConverter()
    info = converter.get_mapping_info()
    print(f"Total DB columns: {info['total_db_columns']}")
    print(f"Mapped DB columns: {info['mapped_db_columns']}")
    print(f"Unmapped DB columns: {info['unmapped_db_columns']}\n")

    print("Loading data from Excel...")
    excel_file = (
        Path(__file__).parent.parent / "dev_data_struct" / "sample_salsify.xlsx"
    )

    try:
        all_sheets = {
            sheet_name: pd.read_excel(excel_file, sheet_name=sheet_name, header=5)
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
        # Include all nutritionalContent slots present in sheet
        for col in df["Angaben_für_die_Lebensmitt"].columns:
            if col.startswith("nutritionalContent") and col not in nutri_cols:
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
                    "TIDFunctionalName[de]",
                    "TIDDescriptionShort[de]",
                    "TIDBrandName",
                    "regulatedProductNameValue[de]",
                ]
            ],
            df["Artikelidentifikation"][
                ["GlobalTradeItemNumber", "NameOfBrandOwner", "targetMarketCountryCode"]
            ],
        ]

        merged_df = reduce(
            lambda left, right: left.merge(
                right, on="GlobalTradeItemNumber", how="outer"
            ),
            dfs_to_merge,
        )

        print(f"Merged dataframe shape: {merged_df.shape}")
        print("Converting column names and extracting nutrients...")
        converted_df = converter.convert(merged_df)

        print(f"Converted dataframe shape: {converted_df.shape}")
        print(f"Converted columns ({len(converted_df.columns)}):")
        for col in converted_df.columns:
            print(f"  - {col}")

        # Preview sample product row 0
        sample_row = converted_df.dropna(subset=["code"]).head(1)
        print("\nSample converted product:")
        for col in [
            "code",
            "brands",
            "brand_owner",
            "branded_food_category",
            "labelNutrients.calories.value",
            "labelNutrients.protein.value",
            "labelNutrients.fat.value",
            "labelNutrients.sugars.value",
            "labelNutrients.sodium.value",
        ]:
            if col in sample_row.columns:
                print(f"  {col}: {sample_row[col].values[0]}")

        output_path = Path(__file__).parent.parent / "loader_output.csv"
        converter.save_converted_data(merged_df, str(output_path), format="csv")

    except FileNotFoundError as e:
        print(f"Error: {e}")
