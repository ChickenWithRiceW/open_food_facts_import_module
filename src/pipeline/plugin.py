import json
import pandas as pd
from pathlib import Path
from typing import Dict, Optional


class ColumnNameConverter:
    """Convert data column names from EDA to database column names using column_mapper.json"""

    def __init__(self, mapper_path: Optional[str] = None):
        """
        Initialize the converter with a column mapper file.
        
        Args:
            mapper_path: Path to column_mapper.json. If None, looks for it in the current directory.
        """
        if mapper_path is None:
            mapper_path = Path(__file__).parent / "column_mapper.json"
        
        self.mapper_path = Path(mapper_path)
        self.db_to_eda_map = self._load_mapper()
        self.eda_to_db_map = self._invert_mapper()

    def _load_mapper(self) -> Dict[str, Optional[str]]:
        """Load the column mapper from JSON file."""
        if not self.mapper_path.exists():
            raise FileNotFoundError(f"Column mapper file not found: {self.mapper_path}")
        
        with open(self.mapper_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _invert_mapper(self) -> Dict[Optional[str], str]:
        """Invert the mapper to go from EDA column names to database column names."""
        inverted = {}
        for db_col, eda_col in self.db_to_eda_map.items():
            if eda_col is not None:
                inverted[eda_col] = db_col
        return inverted

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert DataFrame column names from EDA to database column names.
        
        Args:
            df: DataFrame with EDA column names (as from merged_df in eda.ipynb)
        
        Returns:
            DataFrame with database column names
        """
        # Create a mapping of columns that exist in both df and mapper
        rename_map = {}
        for eda_col in df.columns:
            if eda_col in self.eda_to_db_map:
                db_col = self.eda_to_db_map[eda_col]
                rename_map[eda_col] = db_col
        
        # Rename columns
        converted_df = df.rename(columns=rename_map)
        
        return converted_df

    def get_unmapped_columns(self, df: pd.DataFrame) -> list:
        """
        Get list of columns in DataFrame that don't have a mapping.
        
        Args:
            df: DataFrame to check
        
        Returns:
            List of unmapped column names
        """
        unmapped = [col for col in df.columns if col not in self.eda_to_db_map]
        return unmapped

    def get_mapping_info(self) -> Dict[str, dict]:
        """
        Get information about the mappings.
        
        Returns:
            Dictionary with mapping statistics
        """
        total_db_columns = len(self.db_to_eda_map)
        mapped_eda_columns = len(self.eda_to_db_map)
        unmapped_db_columns = total_db_columns - mapped_eda_columns
        
        return {
            "total_db_columns": total_db_columns,
            "mapped_eda_columns": mapped_eda_columns,
            "unmapped_db_columns": unmapped_db_columns,
            "eda_to_db_map": self.eda_to_db_map
        }

    def save_converted_data(self, df: pd.DataFrame, output_path: str, format: str = "csv") -> None:
        """
        Convert DataFrame and save to file.
        
        Args:
            df: DataFrame with EDA column names
            output_path: Path to save the converted data
            format: File format ('csv', 'excel', or 'parquet')
        """
        converted_df = self.convert(df)
        output_path = Path(output_path)
        
        # Create parent directories if they don't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() == "csv":
            converted_df.to_csv(output_path, index=False, encoding='utf-8')
        elif format.lower() in ["excel", "xlsx"]:
            converted_df.to_excel(output_path, index=False)
        elif format.lower() == "parquet":
            converted_df.to_parquet(output_path, index=False)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'csv', 'excel', or 'parquet'.")
        
        print(f"Converted data saved to: {output_path}")


# Example usage
if __name__ == "__main__":
    import sys
    from functools import reduce
    
    # Initialize converter
    converter = ColumnNameConverter()
    
    # Display mapping information
    info = converter.get_mapping_info()
    print(f"Total DB columns: {info['total_db_columns']}")
    print(f"Mapped EDA columns: {info['mapped_eda_columns']}")
    print(f"Unmapped DB columns: {info['unmapped_db_columns']}\n")
    
    # Load the merged dataframe from Excel
    print("Loading data from Excel...")
    excel_file = "../dev_data_struct/sample_salsify.xlsx"
    
    try:
        all_sheets = {
            sheet_name: pd.read_excel(excel_file, sheet_name=sheet_name, header=5)
            for sheet_name in pd.ExcelFile(excel_file).sheet_names
        }
        
        def clean_sheet_name(sheet_name: str) -> str:
            return sheet_name.split(" - ", 1)[1].replace(", ", "_").replace("  ", " ").replace(" ", "_").replace("&", "").replace("__", "_") if " - " in sheet_name else sheet_name
        
        salsify = {
            clean_sheet_name(sheet_name): df
            for sheet_name, df in all_sheets.items()
        }
        
        df = salsify
        
        # Create the same merged dataframe as in eda.ipynb
        dfs_to_merge = [
            df["Angaben_für_die_Gesundheit"][['GlobalTradeItemNumber',
                                        'HRICompulsoryAdditivesLabelInformation[de]']],
            df["Gefahrgut_Gefahrstoff"][['GlobalTradeItemNumber',
                                    'WSCEDangerousGoodsIndication']],
            df['Artikellogistik'][['GlobalTradeItemNumber','link']],
            df["Angaben_für_die_Lebensmitt"][['GlobalTradeItemNumber',
                                       'ingredientStatementValue[de]',
                                       'FBSNumberOfServingsPerPackage',
                                       'wSCEDietTypeCode',
                                       'allergenTypeCode',
                                       'nutritionalValueReference',
                                       'nutritionalValueReferenceUOM',
                                       'servingSizeValue',
                                       'servingSizeValueUOM',
                                       'calorificValueKcal',
                                       'calorificValueKJ',
                                       'nutritionalContent',
                                       'nutritionalContentQuantityContainedValue',
                                       'nutritionalContentQuantityContainedUOM',
                                       'nutritionalContent.1',
                                       'nutritionalContentQuantityContainedValue.1',
                                       'nutritionalContentQuantityContainedUOM.1',
                                       'nutritionalContent.2',
                                       'nutritionalContentQuantityContainedValue.2',
                                       'nutritionalContentQuantityContainedUOM.2',
                                       'nutritionalContent.3',
                                       'nutritionalContentQuantityContainedValue.3',
                                       'nutritionalContentQuantityContainedUOM.3',
                                       'nutritionalContent.4',
                                       'nutritionalContentQuantityContainedValue.4',
                                       'nutritionalContentQuantityContainedUOM.4',
                                       'nutritionalContent.5',
                                       'nutritionalContentQuantityContainedValue.5',
                                       'nutritionalContentQuantityContainedUOM.5',
                                       'nutritionalContent.6',
                                       'nutritionalContentQuantityContainedValue.6',
                                       'nutritionalContentQuantityContainedUOM.6',
                                       'nutritionalContent.7',
                                       'nutritionalContentQuantityContainedValue.7',
                                       'nutritionalContentQuantityContainedUOM.7',
                                       'nutritionalContent.8',
                                       'nutritionalContentQuantityContainedValue.8',
                                       'nutritionalContentQuantityContainedUOM.8']],
            df["Artikelverpackung"][['GlobalTradeItemNumber',
                                   'IsPackagingMarkedReturnable']],
            df["Artikelmaße"][['GlobalTradeItemNumber',
                                   'NetWeight',
                                   'NetWeightUOM',
                                   'GrossWeightValue',
                                   'GrossWeightUOM']],
            df["Artikelbeschreibung"][['GlobalTradeItemNumber',
                                   'TIDFunctionalName[de]',
                                   'TIDDescriptionShort[de]',
                                   'TIDBrandName',
                                   'regulatedProductNameValue[de]']],
            df["Artikelidentifikation"][['GlobalTradeItemNumber',
                                     'NameOfBrandOwner',
                                     'targetMarketCountryCode']]
        ]
        
        merged_df = reduce(lambda left, right: left.merge(right, on='GlobalTradeItemNumber', how='outer'), dfs_to_merge)
        
        print(f"Merged dataframe shape: {merged_df.shape}")
        print(f"Merged dataframe columns: {len(merged_df.columns)}\n")
        
        # Check for unmapped columns
        unmapped = converter.get_unmapped_columns(merged_df)
        if unmapped:
            print(f"Unmapped columns: {unmapped}\n")
        
        # Convert and save
        print("Converting column names...")
        converted_df = converter.convert(merged_df)
        
        print(f"Converted dataframe columns ({len(converted_df.columns)}):")
        for col in converted_df.columns:
            print(f"  - {col}")
        
        # Save to different formats
        print("\nSaving converted data...")
        converter.save_converted_data(merged_df, "../loader_output.csv", format="csv")
        
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure you're running this script from the pipeline directory")
