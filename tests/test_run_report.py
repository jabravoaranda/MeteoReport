import json
import io
from contextlib import redirect_stdout
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from run_report import ROOT, load_config, main, make_command, month_bounds, month_range


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config.toml")

    def test_month_boundaries_and_invalid_inputs(self):
        self.assertEqual(month_bounds("2024-02"), ("2024-02-01", "2024-03-01"))
        self.assertEqual(month_bounds("2024-12"), ("2024-12-01", "2025-01-01"))
        for value in ["2024", "2024-3", "2024-13", "2024-03-01", "../2024"]:
            with self.assertRaises(ValueError):
                month_bounds(value)

    def test_inclusive_period_and_reversed_limits(self):
        self.assertEqual(month_range("2023-12", "2024-03"), ["2023-12", "2024-01", "2024-02", "2024-03"])
        self.assertEqual(month_range("2024-03", "2024-03"), ["2024-03"])
        with self.assertRaises(ValueError):
            month_range("2024-03", "2024-02")

    def test_range_dry_run_never_launches_or_writes_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            args = ["run_report.py", "mrrpro", "--from-month", "2024-03", "--to-month", "2024-05", "--dry-run", "--output", folder]
            with patch.object(sys, "argv", args), patch("run_report.subprocess.run") as process, redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
                process.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_period_continues_after_error_and_writes_one_index(self):
        with tempfile.TemporaryDirectory() as folder:
            args = ["run_report.py", "meteo", "--from-month", "2024-01", "--to-month", "2024-03",
                    "--continue-on-error", "--open", "--output", folder]
            from subprocess import CompletedProcess
            with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()), \
                 patch("run_report.subprocess.run", side_effect=[CompletedProcess([], 0), CompletedProcess([], 1), CompletedProcess([], 0)]) as process, \
                 patch("run_report.webbrowser.open") as browser:
                self.assertEqual(main(), 1)
                self.assertEqual(process.call_count, 3)
                browser.assert_called_once()
            index = Path(folder) / "meteo" / "periodos" / "2024-01_2024-03" / "informe.html"
            contents = index.read_text(encoding="utf-8")
            self.assertIn("Error (1)", contents)
            self.assertIn("../../2024-03/informe.html", contents)

    def test_period_stops_on_error_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            args = ["run_report.py", "meteo", "--from-month", "2024-01", "--to-month", "2024-03", "--output", folder]
            from subprocess import CompletedProcess
            with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()), \
                 patch("run_report.subprocess.run", return_value=CompletedProcess([], 2)) as process:
                self.assertEqual(main(), 2)
                process.assert_called_once()
            index = Path(folder) / "meteo" / "periodos" / "2024-01_2024-03" / "informe.html"
            self.assertIn("Pendiente", index.read_text(encoding="utf-8"))

    def test_surface_command_uses_same_python_and_safe_arguments(self):
        command, report = make_command("meteo", "2024-03", self.config, source=Path("D:/Datos HDP"))
        self.assertEqual(command[0], sys.executable)
        self.assertIn("D:\\Datos HDP" if sys.platform == "win32" else "D:/Datos HDP", command)
        self.assertIn("2024-04-01", command)
        self.assertEqual(report, ROOT / "informes" / "meteo" / "2024-03" / "informe.html")

    def test_mrr_layer_and_cache_are_explicit(self):
        command, _ = make_command("mrrpro", "2024-03", self.config)
        index = command.index("--layer")
        self.assertEqual(command[index + 1:index + 3], ["640", "840"])
        self.assertIn(str(ROOT / "informes" / "cache" / "mrrpro"), command)
        command, _ = make_command("mrrpro", "2024-03", self.config, phase="--figures-only")
        self.assertIn("--figures-only", command)

    def test_dry_run_does_not_launch_calculations(self):
        with patch.object(sys, "argv", ["run_report.py", "meteo", "--month", "2024-03", "--dry-run"]), \
             patch("run_report.subprocess.run") as process:
            self.assertEqual(main(), 0)
            process.assert_not_called()

    def test_vscode_inputs_and_debug_task_references_exist(self):
        tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
        launch = json.loads((ROOT / ".vscode" / "launch.json").read_text(encoding="utf-8"))
        labels = {task["label"] for task in tasks["tasks"]}
        for configuration in launch["configurations"]:
            self.assertIn(configuration["preLaunchTask"], labels)


if __name__ == "__main__":
    unittest.main()
