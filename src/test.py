from unknown_data import LoadError, LoadOptions, load_file

try:
    result = load_file(
        "sample.json",
        LoadOptions(records_path=("BrandedFoods",)),
    )

    dataframe = result.dataframe
    file_type = result.format

    print(dataframe)
    dataframe.to_csv("loader_output.csv", index=False)

    # Pass these to your Plugin function:
    # your_plugin_function(dataframe, file_type)

except LoadError as exc:
    print(f"{exc.code}: {exc}")