from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from disdrometer import disdrometer_products, intensity_box, write_disdrometer_section
from meteoreport import read_toa5


class DisdrometerTests(unittest.TestCase):
    def test_box_excludes_zeros_and_retains_extremes(self):
        box = intensity_box(pd.Series([0, -1, np.nan, 1, 2, 3, 4, 100]), "month")
        self.assertEqual(box["med"], 3)
        self.assertEqual(box["q1"], 2)
        self.assertEqual(box["q3"], 4)
        self.assertEqual(box["whislo"], 1)
        self.assertEqual(box["whishi"], 4)
        self.assertEqual(box["fliers"], [100])
        self.assertIsNone(intensity_box(pd.Series([0, np.nan]), "month"))

    def test_quality_denominators_and_unknown_codes(self):
        frame = pd.DataFrame({"precipitation": [10, 11, 100, 12, 13],
                              "rain_intensity": [0, 2, 99, 4, -1],
                              "weather_code_wawa": [0, 61, 89, 71, 45],
                              "sensor_status": [0, 0, 1, 0, 0], "error_code": 0},
                             index=pd.date_range("2024-01-01", periods=5, freq="min"))
        products = disdrometer_products(frame, frame, pd.period_range("2024-01", "2024-02", freq="M"))
        january, february = products["mensual"]
        self.assertEqual(january["registros_intensidad_validos"], 3)
        self.assertEqual(january["n_positivos"], 2)
        self.assertAlmostEqual(january["porcentaje_positivos"], 200 / 3)
        self.assertEqual(january["mediana_positiva_mm_h"], 3)
        self.assertEqual(january["intensidad_max_mm_h"], 4)
        self.assertEqual(january["precipitacion_observada_mm"], 2)
        self.assertEqual(february["registros_intensidad_validos"], 0)
        self.assertIsNone(products["boxes"][1])
        types = pd.DataFrame(products["tipos_mensuales"])
        self.assertEqual(types.registros.sum(), 4)
        self.assertNotIn(89, types.codigo.tolist())
        self.assertEqual(types.loc[types.codigo == 71, "tipo"].iloc[0], "Nieve")
        self.assertIn("No clasificado", types.loc[types.codigo == 45, "tipo"].iloc[0])
        with tempfile.TemporaryDirectory() as folder:
            content = write_disdrometer_section(products, Path(folder))
            self.assertIn("Boxplots", content)
            for image in ["disdrometer_boxplot_intensidad.png", "disdrometer_tipos_precipitacion.png",
                          "disdrometer_precipitacion_mensual.png"]:
                self.assertTrue((Path(folder) / image).is_file())

    def test_toa5_uses_neighbouring_counter_and_preserves_reflectivity(self):
        text = '''"TOA5","Station","disdrometer"
"TIMESTAMP","RECORD","precipitation","rain_intensity","weather_code_wawa","radar_reflectivity"
"TS","RN","mm","mm/h","","dBz"
"","","Smp","Smp","Smp","Smp"
"2024-01-31 23:59:00",1,10,0,0,-9.999
"2024-02-01 00:00:00",2,11,2,61,5
"2024-02-01 00:01:00",3,14,4,61,6
'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.dat"
            path.write_text(text, encoding="utf-8")
            result = read_toa5(path, pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-01"))
            self.assertEqual(result[0]["disdrometro"]["mensual"][0]["precipitacion_observada_mm"], 1)
            self.assertEqual(result[1].loc[result[1].variable == "radar_reflectivity", "min"].iloc[0], -9.999)


if __name__ == "__main__":
    unittest.main()
