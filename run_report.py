"""Lanzador mensual para terminal, tareas de VS Code y depuración con F5."""
from __future__ import annotations

import argparse
import calendar
import html
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import sys
import tomllib
import webbrowser
import os
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent


def month_bounds(value):
    if len(value) != 7:
        raise ValueError("El mes debe tener el formato AAAA-MM, por ejemplo 2024-03.")
    date = datetime.strptime(value, "%Y-%m")
    days = calendar.monthrange(date.year, date.month)[1]
    return date.date().isoformat(), (date + timedelta(days=days)).date().isoformat()


def load_config(path):
    with path.open("rb") as file:
        return tomllib.load(file)


def month_range(first, last):
    month_bounds(first)
    month_bounds(last)
    if first > last:
        raise ValueError("El mes inicial debe ser anterior o igual al final.")
    result = []
    current = first
    while current <= last:
        result.append(current)
        _, next_month = month_bounds(current)
        current = next_month[:7]
    return result


def period_index(instrument, months, results, report_root):
    folder = report_root / "periodos" / f"{months[0]}_{months[-1]}"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for month in months:
        report, code = results.get(month, (None, None))
        status = "Pendiente" if code is None else ("Correcto" if code == 0 else f"Error ({code})")
        link = "—"
        if code == 0:
            relative = quote(os.path.relpath(report, folder).replace("\\", "/"))
            link = f"<a href='{relative}'>Abrir informe</a>"
        rows.append(f"<tr><td>{month}</td><td>{status}</td><td>{link}</td></tr>")
    path = folder / "informe.html"
    path.write_text("<!doctype html><html lang='es'><meta charset='utf-8'>"
                    "<title>MeteoReport · periodo</title><style>body{font:16px system-ui;margin:40px}"
                    "td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}</style>"
                    f"<h1>{html.escape(instrument)} · {months[0]} a {months[-1]}</h1>"
                    "<p>Informes independientes por mes. Ambos meses límite están incluidos.</p>"
                    "<table><tr><th>Mes</th><th>Estado</th><th>Resultado</th></tr>"
                    + "".join(rows) + "</table></html>", encoding="utf-8")
    return path


def make_command(instrument, month, config, source=None, output=None, phase=None):
    start, end = month_bounds(month)
    source = Path(source or config["report"]["source"])
    output = Path(output or config["report"]["output"])
    if not output.is_absolute():
        output = ROOT / output
    destination = output / instrument / month
    if instrument == "mrrpro":
        layer = config["mrrpro"]["layer"]
        if len(layer) != 2 or not 0 < layer[0] < layer[1]:
            raise ValueError("mrrpro.layer debe contener dos alturas positivas y crecientes.")
        workers = config["mrrpro"]["workers"]
        if not isinstance(workers, int) or not 1 <= workers <= 8:
            raise ValueError("mrrpro.workers debe ser un entero entre 1 y 8.")
        cache = Path(config["mrrpro"].get("cache", "informes/cache/mrrpro"))
        if not cache.is_absolute():
            cache = ROOT / cache
        args = ["mrrpro.py", "--source", str(source / "mrrpro82"), "--month", month,
                "--layer", *map(str, layer), "--workers", str(workers), "--cache-dir", str(cache)]
        if phase:
            args.append(phase)
    else:
        args = ["meteoreport.py", "--instrument", instrument, "--source", str(source),
                "--start", start, "--end", end]
    args[0] = str(ROOT / args[0])
    return [sys.executable, *args, "--output", str(destination)], destination / "informe.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instrument", choices=["meteo", "disdrometer", "mrrpro", "superficie"])
    parser.add_argument("--month", help="AAAA-MM; por defecto, report.month de config.toml")
    parser.add_argument("--from-month", help="Primer mes del periodo, incluido (AAAA-MM)")
    parser.add_argument("--to-month", help="Último mes del periodo, incluido (AAAA-MM)")
    parser.add_argument("--continue-on-error", action="store_true", help="Continuar con los meses siguientes si alguno falla")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--source", type=Path, help="Carpeta raíz HDP; sustituye la configuración")
    parser.add_argument("--output", type=Path, help="Carpeta raíz de salida; sustituye la configuración")
    parser.add_argument("--open", action="store_true", help="Abrir el informe o índice del periodo al terminar")
    parser.add_argument("--dry-run", action="store_true", help="Mostrar el comando sin leer ni calcular datos")
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--prepare-only", action="store_true", help="MRR-PRO: guardar datos sin generar figuras")
    phase.add_argument("--figures-only", action="store_true", help="MRR-PRO: figuras desde datos preparados, sin leer originales")
    args = parser.parse_args()
    if args.month and (args.from_month or args.to_month):
        parser.error("Use --month o el rango --from-month/--to-month, sin combinarlos.")
    if bool(args.from_month) != bool(args.to_month):
        parser.error("El periodo requiere --from-month y --to-month.")
    if (args.prepare_only or args.figures_only) and args.instrument != "mrrpro":
        parser.error("Las fases separadas están disponibles para mrrpro.")
    if args.prepare_only and args.open:
        parser.error("--prepare-only no genera un informe que abrir; omita --open.")
    try:
        config = load_config(args.config)
        months = month_range(args.from_month, args.to_month) if args.from_month else [args.month or config["report"]["month"]]
        phase = "--prepare-only" if args.prepare_only else ("--figures-only" if args.figures_only else None)
        commands = [(month, *make_command(args.instrument, month, config, args.source, args.output, phase)) for month in months]
        results, failed, target = {}, 0, None
        for number, (month, command, report) in enumerate(commands, 1):
            print(f"[{number}/{len(months)}] {month}", flush=True)
            print(subprocess.list2cmdline(command), flush=True)
            print("Salida: datos preparados en caché" if args.prepare_only else f"Resultado: {report}", flush=True)
            if args.dry_run:
                continue
            # Mismo intérprete del lanzador; lista de argumentos, sin interpretación de shell.
            result = subprocess.run(command, cwd=ROOT, check=False)
            results[month] = (report, result.returncode)
            failed = failed or result.returncode
            target = report
            if len(months) > 1 and not args.prepare_only:
                target = period_index(args.instrument, months, results, report.parent.parent)
            if result.returncode and not args.continue_on_error:
                break
        if not args.dry_run and args.open and target is not None and (len(months) > 1 or not failed):
            webbrowser.open(target.resolve().as_uri())
        return failed
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Error: {error}\n")
    except KeyboardInterrupt:
        print("\nProceso interrumpido.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
