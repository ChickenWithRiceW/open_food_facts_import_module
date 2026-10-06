from pathlib import Path
import re
import pandas as pd


# TODO: Implement base export plugin class!
class OpenFoodFactsExporter:
    """Sanitizes internal DataFrames and exports to Open Food Facts staging format."""

    def __init__(self, delimiter: str = "\t"):
        self.delimiter = delimiter

    def determine_nutrition_base(self, df: pd.DataFrame) -> str:
        """Determines whether the nutrition header reference is 100g or 100ml based on unit mode."""
        unit_candidates = [
            "quantity.serving_quantity_unit",
            "serving_quantity_unit",
            "quantity.product_quantity_unit",
            "product_quantity_unit",
        ]

        for col in unit_candidates:
            if col in df.columns:
                units = df[col].dropna().astype(str).str.strip().str.lower()
                if not units.empty:
                    most_common = units.mode().iloc[0]
                    if "ml" in most_common:
                        return "100ml"

        return "100g"

    def clean_barcode_series(self, series: pd.Series) -> pd.Series:
        """Normalizes barcodes to string format, preventing scientific notation and dropping decimals."""
        numeric_codes = pd.to_numeric(series, errors="coerce")
        int_strings = numeric_codes.dropna().astype("int64").astype(str)

        raw_strings = (
            series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        )
        raw_strings.update(int_strings)
        return raw_strings.replace(["nan", "None", "", "<NA>"], pd.NA)

    def build_column_mapping(
        self, columns: list[str], nutri_base: str
    ) -> dict[str, str]:
        """Maps internal schema paths to official Open Food Facts header names."""
        mapping: dict[str, str] = {}

        for col in columns:
            if col.startswith(("nutrition.nutrients.", "nutrition.nutriments.")):
                clean_path = re.sub(r"^nutrition\.nutri[me]+nts\.", "", col)

                if clean_path.endswith(".value_string"):
                    nutrient = clean_path[:-13]
                    mapping[col] = (
                        f"nutrition.input_set.packaging.as_sold.{nutri_base}.{nutrient}"
                    )
                elif clean_path.endswith(".unit"):
                    nutrient = clean_path[:-5]
                    mapping[col] = (
                        f"nutrition.input_set.packaging.as_sold.{nutri_base}.{nutrient}.unit"
                    )
                else:
                    mapping[col] = (
                        f"nutrition.input_set.packaging.as_sold.{nutri_base}.{clean_path}"
                    )

            elif col.startswith("product_names.product_name."):
                lang = col.split(".")[-1]
                mapping[col] = f"product_name_{lang}"

            elif col.startswith("product_names.generic_name."):
                lang = col.split(".")[-1]
                mapping[col] = f"generic_name_{lang}"

            else:
                mapping[col] = col.split(".")[-1]

        return mapping

    def sanitize_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Applies column sanitization and validates mandatory barcodes."""
        if df.empty:
            return df.copy()

        out_df = df.copy()
        nutri_base = self.determine_nutrition_base(out_df)
        rename_dict = self.build_column_mapping(list(out_df.columns), nutri_base)
        out_df = out_df.rename(columns=rename_dict)

        if "code" not in out_df.columns:
            raise KeyError(
                "DataFrame must contain a 'code' or 'identification.code' column."
            )

        out_df["code"] = self.clean_barcode_series(out_df["code"])
        return out_df.dropna(subset=["code"])

    def export(
        self,
        df: pd.DataFrame,
        output_path: str | Path,
    ) -> Path:
        """Sanitizes and exports the DataFrame to a TSV/CSV file."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

        cleaned_df = self.sanitize_dataframe(df)
        cleaned_df.to_csv(
            out_file,
            sep=self.delimiter,
            index=False,
            encoding="utf-8",
        )
        return out_file


if __name__ == "__main__":
    mock_data = {
        "identification.code": [1633636543505.0, "8906004982514", None],
        "identification.brands": ["MICHELE'S", "VEETEE", "TEST"],
        "identification.brand_owner": ["MICHELE'S", "VEETEE", "TEST"],
        "identification.countries": ["United States", "United States", "United States"],
        "product_names.product_name.en": [
            "GRANOLA, CINNAMON, RAISIN",
            "SUPREME BASMATI RICE",
            "INVALID PRODUCT",
        ],
        "categories_and_labels.categories": ["Cereal", "Rice", "Other"],
        "ingredients_and_allergens.ingredients_text": [
            "ORGANIC ROLLED OATS...",
            "RIZ BASMATI RICE.",
            "UNKNOWN",
        ],
        "quantity.serving_quantity": [28.0, 45.0, 10.0],
        "quantity.serving_quantity_unit": ["g", "g", "ml"],
        "quantity.serving_size": ["0.25 cup", "0.25 cup", "1 piece"],
        "nutrition.nutrients.proteins": [10.7, 8.89, 0.0],
        "nutrition.nutrients.energy-kcal": [500.0, 356.0, 0.0],
        "nutrition.nutrients.sugar": [21.4, 4.44, 0.0],
        "nutrition.nutrients.salt": [0.40, 0.0, 0.0],
    }

    df_sample = pd.DataFrame(mock_data)
    exporter = OpenFoodFactsExporter(delimiter="\t")
    output_target = Path("output/sample_export.tsv")

    saved = exporter.export(df_sample, output_target)
    print(f"Exported to: {saved}")
