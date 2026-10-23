import csv
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from netCDF4 import Dataset

from meteoreport import RADAR_FIELDS, numeric_summary, rainfall_event, read_radar, read_toa5, write_report
from precipitation import precipitation_tables


class ReportTests(unittest.TestCase):
    def test_counter_differences_missing_reset_and_midnight(self):
        index = pd.to_datetime(["2024-01-31 23:59", "2024-02-01 00:00", "2024-02-01 00:01",
                                "2024-02-01 00:02", "2024-02-01 00:03", "2024-02-01 00:04",
                                "2024-02-01 00:06", "2024-02-01 00:07", "2024-02-01 00:08"])
        counter = pd.Series([10, 11, 13, 7999, 15, 16, 40, 0, 3], index=index)
        monthly, daily, quality = precipitation_tables(counter, pd.period_range("2024-01", "2024-02", freq="M"))
        self.assertEqual(monthly.iloc[0].precipitacion_observada_mm, 1)
        self.assertEqual(monthly.iloc[1].precipitacion_observada_mm, 6)
        self.assertEqual(quality["descensos_contador_consecutivos_archivo"], 1)
        self.assertEqual(daily.minutos_validos.sum(), 4)
        self.assertTrue(daily.precipitacion_diaria_mm.isna().all())
        self.assertTrue(monthly.precipitacion_mensual_mm.isna().all())

    def test_full_dry_day_and_complete_month_use_boundary_reading(self):
        # 29 días de febrero bisiesto, más la lectura inicial para la diferencia.
        index = pd.date_range("2024-02-01", "2024-03-01", freq="min")
        counter = pd.Series(0., index=index)
        monthly, daily, _ = precipitation_tables(counter, pd.period_range("2024-02", "2024-02", freq="M"),
                                                  pd.Timestamp("2024-02-01"), pd.Timestamp("2024-03-01"))
        self.assertTrue(daily.completo.all())
        self.assertEqual(len(daily), 29)
        self.assertEqual(monthly.iloc[0].precipitacion_mensual_mm, 0)
        self.assertEqual(monthly.iloc[0].cobertura_pct, 100)
        # Una lectura ausente invalida las dos diferencias colindantes.
        counter.iloc[100] = 7999
        monthly, daily, _ = precipitation_tables(counter, pd.period_range("2024-02", "2024-02", freq="M"))
        self.assertEqual(daily.iloc[0].minutos_validos, 1438)
        self.assertEqual(monthly.iloc[0].dias_completos, 28)
        self.assertTrue(pd.isna(monthly.iloc[0].precipitacion_mensual_mm))

    def test_meteo_7999_defaults_to_nan_and_precipitation_export(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "meteo.dat"
            with path.open("w", newline="", encoding="utf-8") as file:
                csv.writer(file).writerows([
                    ["TOA5", "Station", "meteo"], ["TIMESTAMP", "RECORD", "totalNTR", "intTR_Max"],
                    ["TS", "RN", "mm", "mm/min"], ["", "", "Smp", "Max"],
                    ["2024-01-01 00:00:00", 1, 10, 0],
                    ["2024-01-01 00:01:00", 2, 12, 2],
                    ["2024-01-01 00:02:00", 3, 7999, 7999],
                ])
            result = read_toa5(path)
            self.assertEqual(result[1].iloc[0]["ausentes"], 1)
            self.assertEqual(result[1].iloc[1]["max"], 2)
            self.assertEqual(result[0]["precipitacion"]["mensual"][0]["precipitacion_observada_mm"], 2)
            report = write_report({"meteo": result}, Path(folder) / "out")
            self.assertTrue((report.parent / "precipitacion_mensual.png").exists())
            self.assertTrue((report.parent / "meteo_precipitacion_diaria.csv").exists())

    def test_missing_zeros_percentiles_and_sample_deviation(self):
        result = numeric_summary(pd.Series([0, 2, 4, np.inf, "bad"]))
        self.assertEqual(result["validos"], 3)
        self.assertEqual(result["ausentes"], 2)
        self.assertEqual(result["media"], 2)
        self.assertEqual(result["desv_est"], 2)
        self.assertAlmostEqual(result["p95"], 3.8)

    def test_toa5_filter_duplicates_categories_and_explicit_sentinel(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.dat"
            with path.open("w", newline="", encoding="utf-8") as file:
                csv.writer(file).writerows([
                    ["TOA5", "Station", "meteo"],
                    ["TIMESTAMP", "RECORD", "temperature", "sensor_status", "N(1)"],
                    ["TS", "RN", "degC", "", ""], ["", "", "Smp", "Smp", "Smp"],
                    ["2024-01-01 00:00:00", 1, -9.999, 0, 1],
                    ["2024-01-01 00:01:00", 2, 0, 0, 1],
                    ["2024-01-01 00:01:00", 3, 999, 4, 1],
                    ["invalid", 4, 5, 0, 1],
                    ["2024-01-01 00:03:00", 5, "bad", 1, 1],
                    ["2024-01-02 00:00:00", 6, 100, 1, 1],
                ])
            args = (path, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02"))
            meta, stats, daily, codes = read_toa5(*args)
            self.assertEqual(meta["registros"], 3)
            self.assertEqual(meta["duplicados_periodo_descartados"], 1)
            self.assertEqual(meta["fechas_invalidas_archivo"], 1)
            self.assertEqual(meta["cobertura_temporal_pct"], 75)
            self.assertEqual(meta["columnas_omitidas_espectros"], 1)
            self.assertEqual(stats.iloc[0]["min"], -9.999)
            self.assertEqual(len(codes), 2)
            _, excluded, _, _ = read_toa5(*args, exclusions={"temperature": [-9.999]})
            self.assertEqual(excluded.iloc[0]["validos"], 1)
            report = write_report({"test": (meta, stats, daily, codes)}, Path(folder) / "out")
            self.assertTrue(report.exists())
            self.assertTrue((report.parent / "test_mensual.csv").exists())
            self.assertEqual(daily.iloc[0]["mes"], "2024-01")
            self.assertEqual(daily.iloc[0]["esperados_mes"], 31 * 1440)
            self.assertEqual(daily.iloc[0]["n"], 3)

    def test_monthly_missing_month_is_not_zero_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.dat"
            with path.open("w", newline="", encoding="utf-8") as file:
                csv.writer(file).writerows([
                    ["TOA5", "Station", "meteo"], ["TIMESTAMP", "RECORD", "rain"],
                    ["TS", "RN", "mm"], ["", "", "Smp"],
                    ["2024-01-01 00:00:00", 1, 2], ["2024-03-01 00:00:00", 2, 5],
                ])
            _, _, monthly, _ = read_toa5(path)
            february = monthly[monthly.mes == "2024-02"].iloc[0]
            self.assertEqual(february["esperados_mes"], 29 * 1440)
            self.assertEqual(february["cobertura_valida_mes_pct"], 0)
            self.assertTrue(pd.isna(february["media"]))

    def test_event_selects_one_maximum_and_rejects_gaps_and_suspect_values(self):
        index = pd.date_range("2024-01-01", periods=5, freq="min")
        series = pd.Series([20, 20, 20, 1, 1], index=index)
        event = rainfall_event(series, 50, hours=3 / 60)
        self.assertEqual(event["acumulado_mm"], 60)
        self.assertEqual(event["inicio_inclusivo"], "2024-01-01 00:00:00")
        self.assertNotIn("acumulado_mm", rainfall_event(series, 100, hours=3 / 60))
        self.assertNotIn("acumulado_mm", rainfall_event(series.drop(index[2]), 50, hours=3 / 60))
        series.iloc[2] = 7999
        self.assertNotIn("acumulado_mm", rainfall_event(series, 50, hours=3 / 60))

    def test_radar_masks_time_filter_and_separate_ranges(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            day = root / "2024" / "202401" / "20240101"
            day.mkdir(parents=True)
            with Dataset(day / "20240101_000000.nc", "w") as data:
                data.createDimension("time", 3)
                data.createDimension("range", 2)
                time = data.createVariable("time", "f8", ("time",))
                time.units = "seconds since 2024-01-01T00:00:00Z"
                time[:] = [0, 30, 60]
                data.createVariable("range", "f8", ("range",))[:] = [640, 675]
                for name in RADAR_FIELDS:
                    field = data.createVariable(name, "f8", ("time", "range"), fill_value=-9999)
                    field.units = "test"
                    field[:] = [[0, 10], [2, -9999], [100, 100]]
            meta, stats, _, _ = read_radar(root, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01 00:01:00"))
            self.assertEqual(meta["registros"], 2)
            first = stats[stats.variable == "RR"]
            self.assertEqual(first.iloc[0]["media"], 1)
            self.assertEqual(first.iloc[1]["media"], 10)
            self.assertEqual(first.iloc[1]["ausentes"], 1)
            with self.assertRaises(ValueError):
                read_radar(root, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02"), max_files=0)


if __name__ == "__main__":
    unittest.main()
