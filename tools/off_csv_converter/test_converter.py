"""Run: python3 -m unittest -v test_converter.py"""

import json
import tempfile
import unittest
from pathlib import Path

from convert_off import convert, nutrient_list, read_csv


class ConverterTests(unittest.TestCase):
    def usda(self, **changes):
        row = {"gtinUpc": "001234567890", "description": "Banana, snack",
               "ingredients": "NA", "servingSize": "28", "servingSizeUnit": "g",
               "foodNutrients": repr([
                   {"nutrient": {"id": 2000, "unitName": "g"}, "amount": 21.4},
                   {"nutrient": {"id": 1093, "unitName": "mg"}, "amount": 161},
                   {"nutrient": {"id": 1008, "unitName": "kcal"}, "amount": 500},
               ]), "labelNutrients.sugars.value": "5.99"}
        row.update(changes)
        return row

    def german(self, **changes):
        row = {"GlobalTradeItemNumber": "04104420073685", "TIDDescriptionShort[de]": "Käse",
               "ingredientStatementValue[de]": "MILCH", "TargetMarketCountryCode": "276",
               "nutritionalValueReference": "100", "nutritionalValueReferenceUOM": "GRM",
               "nutritionalContent": "SUGAR", "nutritionalContentQuantityContainedValue": "2,5",
               "nutritionalContentQuantityContainedUOM": "GRM", "NetWeight": "125",
               "NetWeightUOM": "GRM"}
        row.update(changes)
        return row

    def test_usda_identity_units_and_basis(self):
        row = self.usda()
        _, rows, report = convert(list(row), [row])
        self.assertEqual(report["profile"], "usda")
        self.assertEqual(rows[0]["code"], "001234567890")
        self.assertEqual(rows[0]["ingredients_text_en"], "NA")
        self.assertEqual(rows[0]["sugars_100g_g"], "21.4")
        self.assertEqual(rows[0]["sodium_100g_mg"], "161")
        self.assertEqual(rows[0]["energy_100g_kcal"], "500")
        self.assertNotIn("salt_100g_g", rows[0])
        self.assertIn("labelNutrients.sugars.value", report["not_exported_source_columns"])

    def test_source_strings_preserved(self):
        row = self.usda(description="  Banana, \"snack\"\nNew line  ")
        self.assertEqual(convert(list(row), [row])[1][0]["product_name_en"], row["description"])

    def test_no_numeric_coercion_of_values(self):
        row = self.usda(foodNutrients=json.dumps([
            {"nutrient": {"id": 2000, "unitName": "g"}, "amount": "banana"}
        ]))
        self.assertEqual(convert(list(row), [row])[1][0]["sugars_100g_g"], "banana")

    def test_unsupported_nutrient_reported(self):
        row = self.usda(foodNutrients='[{"nutrient":{"id":1104,"unitName":"IU"},"amount":5}]')
        self.assertEqual(len(convert(list(row), [row])[2]["issues"]), 1)

    def test_missing_source_unit_is_not_guessed(self):
        row = self.usda(foodNutrients='[{"nutrient":{"id":2000},"amount":5}]')
        _, rows, report = convert(list(row), [row])
        self.assertNotIn("sugars_100g_g", rows[0])
        self.assertTrue(report["issues"])

    def test_non_gram_usda_is_reported(self):
        row = self.usda(servingSizeUnit="ml")
        _, rows, report = convert(list(row), [row])
        self.assertNotIn("sugars_100g_g", rows[0])
        self.assertTrue(report["issues"])

    def test_german_uses_identifier_not_position(self):
        row = self.german()
        _, rows, _ = convert(list(row), [row])
        self.assertEqual(rows[0]["sugars_100g_g"], "2,5")
        self.assertNotIn("fat_100g_g", rows[0])
        self.assertEqual(rows[0]["ingredients_text_de"], "MILCH")
        self.assertEqual(rows[0]["net_weight"], "125 g")
        self.assertEqual(rows[0]["countries"], "en:germany")

    def test_renamed_german_columns(self):
        row = self.german()
        row["code"] = row.pop("GlobalTradeItemNumber")
        row["labelNutrients.fat.value"] = row.pop("nutritionalContentQuantityContainedValue")
        self.assertEqual(convert(list(row), [row])[1][0]["sugars_100g_g"], "2,5")

    def test_german_template_rows_reported(self):
        row = self.german()
        _, rows, report = convert(list(row), [self.german(GlobalTradeItemNumber="Muss"), row])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(report["skipped_source_rows"]), 1)

    def test_reference_not_assumed(self):
        row = self.german(nutritionalValueReference="30")
        _, rows, report = convert(list(row), [row])
        self.assertNotIn("sugars_100g_g", rows[0])
        self.assertTrue(report["issues"])

    def test_country_is_not_language_or_contact_country(self):
        row = self.german(TargetMarketCountryCode="", targetMarketCountryCode="276")
        _, rows, _ = convert(list(row), [row])
        self.assertNotIn("countries", rows[0])
        self.assertEqual(rows[0]["lc"], "de")

    def test_duplicate_products_fail(self):
        row = self.usda()
        with self.assertRaisesRegex(ValueError, "Duplicate barcode"):
            convert(list(row), [row, row])

    def test_malformed_list_not_executed(self):
        with self.assertRaises((ValueError, SyntaxError)):
            nutrient_list('__import__("os").system("echo unsafe")')

    def test_csv_reading_preserves_literals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.csv"
            path.write_text('code;name;note\n00123;"Apple; juice";NaN\n', encoding="utf-8")
            _, rows = read_csv(path)
            self.assertEqual(rows[0], {"code": "00123", "name": "Apple; juice", "note": "NaN"})

    def test_ragged_csv_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.csv"
            path.write_text("code,name\n001\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_csv(path, ",")


if __name__ == "__main__":
    unittest.main()
