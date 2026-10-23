from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from netCDF4 import Dataset

from mrrpro import FIELDS, level_summary, load_month, radar_box, save_prepared, load_prepared, build_report


class MrrProTests(unittest.TestCase):
    def test_prepared_data_produces_figures_without_any_source_access(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path("Z:/unidad_no_disponible/mrrpro82")
            cache, output = Path(folder) / "cache", Path(folder) / "report"
            month = pd.Period("2024-03", freq="M")
            times = pd.date_range("2024-03-01", periods=2, freq="30s").as_unit("ns").asi8
            values = np.array([[[0, 0, np.nan, np.nan, np.nan], [2, .2, -5, -1, .3]],
                               [[0, 0, np.nan, np.nan, np.nan], [4, .4, 5, 2, .5]]])
            metadata = {"mes": str(month), "niveles_m": [640., 675.],
                        "unidades_originales": {"RR": "mm/h", "LWC": "g m-3", "Ze": "dBZ", "VEL": "m/s", "WIDTH": "m/s"}}
            saved = save_prepared(source, month, (640., 840.), cache, times, values, metadata)
            self.assertTrue(saved.is_file())
            with patch("mrrpro.month_files", side_effect=AssertionError("No debe listar originales")), \
                 patch("mrrpro.Dataset", side_effect=AssertionError("No debe abrir NetCDF")):
                report = build_report(source, month, (640., 840.), output, cache_directory=cache, figures_only=True)
                self.assertTrue(report.is_file())
                self.assertTrue((output / "mrrpro_mensual.csv").is_file())
            with self.assertRaises(ValueError):
                load_prepared(source, pd.Period("2024-04", freq="M"), (640., 840.), cache)
            with patch("mrrpro.prepare_month", return_value=(times, values, metadata)), patch("mrrpro.plot_month") as plot:
                prepared = build_report(source, month, (640., 840.), output, cache_directory=cache, prepare_only=True)
                self.assertEqual(prepared, saved)
                plot.assert_not_called()

    def test_layer_median_per_instant_ignores_cells_without_reflectivity(self):
        month = pd.Period("2024-03", freq="M")
        values = np.array([
            [[999, 999, np.nan, np.nan, np.nan], [2, .2, -5, -1, .3], [8, .8, 5, 3, .7]],
            [[0, 0, np.nan, np.nan, np.nan], [4, .4, -1, -2, .5], [999, 999, np.nan, np.nan, np.nan]],
        ])
        times = pd.date_range("2024-03-01", periods=2, freq="30s").as_unit("ns").asi8
        table, _ = level_summary(times, values, month, [640., 675., 710.], (640., 840.))
        rr = table.set_index("variable").loc["RR"]
        self.assertEqual(rr["registros_usados"], 2)
        self.assertEqual(rr["mediana"], 4.5)  # Median of per-instant medians [5, 4], not pooled gates.
        self.assertEqual(rr["min"], 4)
        self.assertEqual(rr["max"], 5)
        self.assertEqual(rr["mediana_niveles_contribuyentes"], 1.5)

    def test_no_echo_zeros_are_not_valid_rain_and_signed_values_are_preserved(self):
        month = pd.Period("2024-03", freq="M")
        values = np.array([[[0, 0, np.nan, np.nan, np.nan]],
                           [[2, .2, -5, -1, .3]], [[-1, .3, 10, 2, -.5]]])
        times = pd.date_range("2024-03-01", periods=3, freq="30s").as_unit("ns").asi8
        table, boxes = level_summary(times, values, month, [640.], 640.)
        indexed = table.set_index("variable")
        self.assertEqual(indexed.loc["RR", "registros_usados"], 1)
        self.assertEqual(indexed.loc["RR", "registros_numericos_originales"], 3)
        self.assertEqual(indexed.loc["Ze", "min"], -5)
        self.assertEqual(indexed.loc["VEL", "min"], -1)
        self.assertEqual(indexed.loc["WIDTH", "registros_usados"], 1)
        self.assertEqual(indexed.loc["RR", "esperados_mes_30s"], 31 * 2880)
        self.assertEqual(boxes[2]["med"], 2.5)

    def test_radar_box_includes_zero_and_negative_reflectivity(self):
        box = radar_box(pd.Series([-5, 0, 1, 2, 100]), "Ze")
        self.assertEqual(box["med"], 1)
        self.assertEqual(box["whislo"], 0)
        self.assertEqual(box["whishi"], 2)
        self.assertEqual(box["fliers"], [-5, 100])

    def test_month_loader_masks_exact_levels_duplicates_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            day = root / "2024" / "03" / "01"
            day.mkdir(parents=True)
            for hour in [0, 1]:
                with Dataset(day / f"20240301_{hour:02d}0000.nc", "w") as data:
                    data.createDimension("time", 2)
                    data.createDimension("range", 2)
                    data.createVariable("range", "f8", ("range",))[:] = [640, 675]
                    data.variables["range"].units = "meters"
                    time = data.createVariable("time", "f8", ("time",))
                    time.units = "seconds since 1970-01-01T00:00:00Z"
                    base = pd.Timestamp("2024-03-01").timestamp()
                    time[:] = [base + .014, base + 30.014]
                    data.createVariable("elevation", "f8", ("time",))[:] = 90
                    for field in FIELDS:
                        var = data.createVariable(field, "f8", ("time", "range"), fill_value=-9999)
                        var.units = {"RR": "mm/h", "LWC": "g m-3", "Ze": "dBZ", "VEL": "m/s", "WIDTH": "m/s"}[field]
                        var[:] = [[-9999, 2], [-9999, 4]]
            month = pd.Period("2024-03", freq="M")
            times, values, meta = load_month(root, month, [640., 675.], root / "cache")
            self.assertEqual(len(times), 2)
            self.assertEqual(meta["duplicados_30s_descartados"], 2)
            self.assertTrue(np.isnan(values[:, 0]).all())
            self.assertEqual(values[1, 1, 0], 4)
            _, cached, _ = load_month(root, month, [640., 675.], root / "cache")
            np.testing.assert_equal(values, cached)
            with self.assertRaises(ValueError):
                load_month(root, month, [500.], root / "other_cache")


if __name__ == "__main__":
    unittest.main()
