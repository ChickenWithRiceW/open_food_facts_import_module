from abc import ABC, abstractmethod
import json

import ijson
import pandas as pd


# -----------------------------
# Output plugin interface
# -----------------------------

class OutputPlugin(ABC):

    @abstractmethod
    def write(self, df: pd.DataFrame) -> None:
        pass


# -----------------------------
# CSV output plugin
# -----------------------------

class CsvOutputPlugin(OutputPlugin):

    def __init__(self, path: str):
        self.path = path
        self.first_chunk = True

    def write(self, df: pd.DataFrame) -> None:
        df.to_csv(
            self.path,
            mode="w" if self.first_chunk else "a",
            header=self.first_chunk,
            index=False,
            sep="\t",
        )

        self.first_chunk = False


# -----------------------------
# Mapping
# -----------------------------

with open("test.json", "r") as file:
    COLUMN_MAPPING = json.load(file)


# def map_dataframe(df: pd.DataFrame) -> pd.DataFrame:
#     mapping = {
#         source: target
#         for target, source in COLUMN_MAPPING.items()
#         if source is not None and source in df.columns
#     }

#     return df[list(mapping)].rename(columns=mapping)

def map_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=df.index)

    for source, target in COLUMN_MAPPING.items():

        # ---------------------------------
        # foodNutrients special case
        # ---------------------------------
        if source.startswith("foodNutrients."):
            parts = source.split(".", 2)

            # foodNutrients.<nutrient name>.<value path>
            if len(parts) != 3:
                continue

            nutrient_name = parts[1]
            value_path = parts[2]

            def extract(nutrients):
                if not isinstance(nutrients, list):
                    return None

                for nutrient in nutrients:
                    if nutrient.get("nutrient", {}).get("name") == nutrient_name:

                        value = nutrient

                        for key in value_path.split("."):
                            if not isinstance(value, dict):
                                return None

                            value = value.get(key)

                        return value

                return None

            if "foodNutrients" in df.columns:
                result[target] = df["foodNutrients"].apply(extract)

        # ---------------------------------
        # Normal flattened column
        # ---------------------------------
        elif target in df.columns:
            result[source] = df[target]
    print(result.columns.to_list())
    return result


# -----------------------------
# Chunk generator
# -----------------------------

def dataframe_chunks(
    path: str,
    json_key: str,
    chunk_size: int = 10_000,
):
    batch = []

    with open(path, "rb") as file:
        foods = ijson.items(
            file,
            f"{json_key}.item"
        )

        for food in foods:
            batch.append(food)

            if len(batch) >= chunk_size:
                yield pd.json_normalize(batch)
                batch = []

        if batch:
            yield pd.json_normalize(batch)


# -----------------------------
# Pipeline
# -----------------------------

def process(
    input_path: str,
    output_plugin: OutputPlugin,
    json_key: str,
    chunk_size: int = 10_000,
):
    for df in dataframe_chunks(
        input_path,
        json_key,
        chunk_size,
    ):
        # print(df.columns.to_list())
        # print(pd.json_normalize(df["foodNutrients"]))
        # print(pd.json_normalize(df["foodNutrients"][0])["nutrient.name"])

        # exit()
        mapped_df = map_dataframe(df)

        output_plugin.write(mapped_df)


# -----------------------------
# Run
# -----------------------------

output = CsvOutputPlugin("foods.csv")

process(
    input_path="sample.json",
    output_plugin=output,
    json_key="BrandedFoods",
    chunk_size=10_000,
)
