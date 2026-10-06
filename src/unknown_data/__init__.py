"""Raw file ingestion; product schema mapping belongs to a later stage."""

from unknown_data.loader import ImportResult, LoadError, LoadOptions, load_file

__all__ = ["ImportResult", "LoadError", "LoadOptions", "load_file"]
