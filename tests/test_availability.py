import tempfile
import unittest
from pathlib import Path

import pandas as pd

from availability import collect_availability, generate, month_range


class AvailabilityTests(unittest.TestCase):
    def write_csv(self, root, relative, rows):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")

    def test_generates_common_products_without_reading_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reports = root / "informes"
            document = root / "documento"
            month = "2026-01"
            self.write_csv(reports, f"meteo/{month}/meteo_precipitacion_mensual.csv",
                           [{"mes": month, "cobertura_pct": 50}])
            self.write_csv(reports, f"disdrometer/{month}/disdrometer_estudio_mensual.csv",
                           [{"mes": month, "cobertura_pct": 25,
                             "cobertura_intensidad_pct": 75}])
            self.write_csv(reports, f"mrrpro/{month}/mrrpro_mensual.csv", [
                {"mes": month, "variable": field, "cobertura_temporal_pct": 80,
                 "cobertura_valida_pct": 10 * number}
                for number, field in enumerate(("RR", "LWC", "Ze", "VEL", "WIDTH"), 1)
            ])

            months = month_range("2026-01", "2026-02")
            values = collect_availability(reports, months).set_index(["mes", "producto"])
            self.assertEqual(values.loc[(month, "pluviometro"), "cobertura_pct"], 50)
            self.assertEqual(values.loc[(month, "parsivel_intensidad"), "cobertura_pct"], 75)
            self.assertEqual(values.loc[(month, "mrr_temporal"), "cobertura_pct"], 80)
            self.assertEqual(values.loc[(month, "mrr_WIDTH"), "cobertura_pct"], 50)
            self.assertTrue(pd.isna(values.loc[("2026-02", "pluviometro"), "cobertura_pct"]))

            figure, table = generate(reports, document, "2026-01", "2026-02")
            self.assertTrue(figure.is_file())
            contents = table.read_text(encoding="utf-8")
            self.assertIn("2026-01 & 50,0 & 25,0 & 75,0 & 80,0", contents)
            self.assertIn("2026-02 & --- & ---", contents)

    def test_rejects_incompatible_prepared_table(self):
        with tempfile.TemporaryDirectory() as folder:
            reports = Path(folder)
            path = reports / "meteo/2026-01/meteo_precipitacion_mensual.csv"
            path.parent.mkdir(parents=True)
            pd.DataFrame([{"mes": "2026-01"}]).to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "cobertura_pct"):
                collect_availability(reports, month_range("2026-01", "2026-01"))


if __name__ == "__main__":
    unittest.main()
