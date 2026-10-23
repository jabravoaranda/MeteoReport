"""Informes descriptivos de los archivos de Hoya de Pedraza (lectura solamente)."""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from precipitation import plot_precipitation, precipitation_tables
from disdrometer import disdrometer_products, write_disdrometer_section


CATEGORIES = {"weather_code_wawa", "sensor_status", "error_code"}
COUNTERS = {"precipitation", "totalNTR", "bucketTR", "bucketNTR"}
RADAR_FIELDS = ("Za", "Z", "Zea", "Ze", "RR", "LWC", "PIA", "VEL", "WIDTH", "SNR")


def date_arg(value):
    result = pd.Timestamp(value)
    if pd.isna(result) or result.tzinfo is not None:
        raise argparse.ArgumentTypeError("Use una fecha ISO sin zona horaria.")
    return result


def select_time(times, start=None, end=None):
    mask = ~times.isna()
    if start is not None:
        mask &= times >= start
    if end is not None:
        mask &= times < end
    return mask


def numeric_summary(series):
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid = values.dropna()
    return {
        "n": len(values), "validos": len(valid), "ausentes": int(values.isna().sum()),
        "media": valid.mean(), "desv_est": valid.std(ddof=1),
        "min": valid.min(), "p05": valid.quantile(.05),
        "mediana": valid.median(), "p95": valid.quantile(.95), "max": valid.max(),
    }


def rainfall_event(series, threshold_mm=50, hours=72):
    """Mayor ventana completa; el canal debe contener incrementos en mm por minuto."""
    minutes = hours * 60
    if threshold_mm <= 0 or minutes < 1 or not float(minutes).is_integer():
        raise ValueError("El umbral debe ser positivo y la ventana un número entero de minutos.")
    series = series.sort_index()
    if series.empty:
        return {"estado": "Sin datos para buscar un evento"}
    if not (series.index == series.index.floor("min")).all():
        raise ValueError("El canal de evento debe tener marcas de tiempo en minutos exactos.")
    # No rellenar con cero los minutos ausentes ni aceptar códigos sospechosos.
    series = series.where(np.isfinite(series) & (series >= 0) & ~series.isin([7999, -9.999]))
    series = series.reindex(pd.date_range(series.index.min(), series.index.max(), freq="min"))
    totals = series.rolling(int(minutes), min_periods=int(minutes)).sum()
    result = {"umbral_mm": threshold_mm, "ventana_horas": hours,
              "criterio": "Ventana móvil completa, sin minutos ausentes; umbral inclusivo. "
                          "Canal de incrementos elegido explícitamente por el usuario."}
    if not totals.notna().any():
        return {**result, "estado": "No evaluable: ninguna ventana completa válida"}
    peak_end = totals.idxmax()
    peak = float(totals.loc[peak_end])
    if peak < threshold_mm:
        return {**result, "estado": "Sin evento que alcance el umbral en las ventanas evaluables",
                "mayor_acumulado_mm": peak}
    return {**result, "estado": "Evento candidato para revisión", "acumulado_mm": peak,
            "inicio_inclusivo": str(peak_end - pd.Timedelta(minutes=int(minutes) - 1)),
            "fin_exclusivo": str(peak_end + pd.Timedelta(minutes=1))}


def read_toa5(path, start=None, end=None, exclusions=None, event_column=None,
              event_threshold=50, event_hours=72):
    with path.open(encoding="utf-8-sig", errors="strict", newline="") as stream:
        reader = csv.reader(stream)
        header, names, units, processing = [next(reader) for _ in range(4)]
    if header[0] != "TOA5" or names[:2] != ["TIMESTAMP", "RECORD"]:
        raise ValueError(f"Cabecera TOA5 no compatible: {path}")
    if len(units) != len(names) or len(processing) != len(names):
        raise ValueError(f"Metadatos desalineados: {path}")
    # Las distribuciones y los espectros necesitan un análisis específico por clases.
    selected = [n for n in names if not n.startswith(("N(", "V(", "spectrum("))]
    frame = pd.read_csv(path, skiprows=4, names=names, usecols=selected,
                        na_values=["NAN", "NaN", "INF", "-INF"], low_memory=False)
    times = pd.DatetimeIndex(pd.to_datetime(frame.pop("TIMESTAMP"), errors="coerce", format="%Y-%m-%d %H:%M:%S"))
    invalid_times = int(times.isna().sum())
    frame.index = times
    # Mantener las lecturas vecinas permite cerrar el primer y último minuto del filtro.
    full_counter = frame.loc[~frame.index.isna(), "totalNTR"].copy() if "totalNTR" in frame else None
    is_disdrometer = {"rain_intensity", "precipitation", "weather_code_wawa"}.issubset(frame.columns)
    full_disdrometer = frame.loc[~frame.index.isna()].copy() if is_disdrometer else None
    frame = frame.loc[select_time(times, start, end)].sort_index(kind="stable")
    duplicates = int(frame.index.duplicated().sum())
    frame = frame.loc[~frame.index.duplicated(keep="first")].drop(columns="RECORD")
    nonnumeric = {}
    replaced_7999 = {}
    for name in frame:
        original = frame[name]
        frame[name] = pd.to_numeric(original, errors="coerce").replace([np.inf, -np.inf], np.nan)
        nonnumeric[name] = int((original.notna() & frame[name].isna()).sum())
        if "totalNTR" in frame:
            replaced_7999[name] = int((frame[name] == 7999).sum())
            frame.loc[frame[name] == 7999, name] = np.nan
        for marker in (exclusions or {}).get(name, []):
            frame.loc[frame[name] == marker, name] = np.nan
    unit_map = dict(zip(names, units))
    rows, frequencies = [], []
    for name in frame:
        if name in CATEGORIES:
            for value, count in frame[name].value_counts(dropna=False).items():
                frequencies.append({"variable": name, "codigo": value, "n": int(count)})
        else:
            rows.append({"variable": name, "unidad": unit_map[name],
                         "tipo": "contador/nivel" if name in COUNTERS else "medida",
                         **numeric_summary(frame[name])})
    periods = []
    first = start if start is not None else (frame.index.min() if len(frame) else None)
    last = end - pd.Timedelta(nanoseconds=1) if end is not None else (frame.index.max() if len(frame) else None)
    months = pd.period_range(first, last, freq="M") if first is not None and last is not None else []
    for month in months:
        block = frame.loc[frame.index.to_period("M") == month]
        expected_month = month.days_in_month * 1440
        for name in frame:
            if name not in CATEGORIES:
                stats = numeric_summary(block[name])
                periods.append({"mes": str(month), "variable": name,
                                "unidad": unit_map[name], **stats,
                                "esperados_mes": expected_month,
                                "cobertura_temporal_mes_pct": 100 * len(block) / expected_month,
                                "cobertura_valida_mes_pct": 100 * stats["validos"] / expected_month})
    gaps = frame.index.to_series().diff().dt.total_seconds().dropna()
    # La cobertura se calcula solo sobre el intervalo observado y la cadencia indicada.
    expected = int((frame.index.max() - frame.index.min()).total_seconds() / 60) + 1 if len(frame) else 0
    regular = bool((gaps % 60 == 0).all())
    meta = {
        "archivo": str(path), "estacion_cabecera": header[1], "tabla": header[-1],
        "inicio": str(frame.index.min()) if len(frame) else None,
        "fin": str(frame.index.max()) if len(frame) else None,
        "registros": len(frame), "fechas_invalidas_archivo": invalid_times,
        "duplicados_periodo_descartados": duplicates,
        "cadencia_nominal_segundos": 60,
        "huecos_mayores_60s": int((gaps > 60).sum()),
        "mayor_salto_segundos": float(gaps.max()) if len(gaps) else None,
        "cobertura_temporal_pct": 100 * len(frame) / expected if expected and regular else None,
        "zona_horaria": "No declarada en TOA5; se conserva la hora original",
        "columnas_omitidas_espectros": len(names) - len(selected),
        "conversiones_no_numericas": nonnumeric,
        "valores_menos_9_999": {n: int((frame[n] == -9.999).sum()) for n in frame if (frame[n] == -9.999).any()},
        "valores_7999_revisar": {n: int((frame[n] == 7999).sum()) for n in frame if (frame[n] == 7999).any()},
        "exclusiones_configuradas": exclusions or {},
        "valores_7999_convertidos_nan": replaced_7999,
    }
    if full_counter is not None and len(months):
        if unit_map["totalNTR"] != "mm":
            raise ValueError("Se esperan unidades mm para totalNTR.")
        full_counter = pd.to_numeric(full_counter, errors="coerce")
        for marker in (exclusions or {}).get("totalNTR", []):
            full_counter = full_counter.mask(full_counter == marker)
        rain_monthly, rain_daily, rain_quality = precipitation_tables(full_counter, months, start, end)
        meta["precipitacion"] = {**rain_quality, "mensual": rain_monthly.to_dict("records"),
                                "diaria": rain_daily.assign(fecha=rain_daily.fecha.astype(str)).to_dict("records")}
    if is_disdrometer and len(months):
        if unit_map["precipitation"] != "mm" or unit_map["rain_intensity"] != "mm/h":
            raise ValueError("Se esperan mm para precipitation y mm/h para rain_intensity.")
        for name in full_disdrometer:
            full_disdrometer[name] = pd.to_numeric(full_disdrometer[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
            for marker in (exclusions or {}).get(name, []):
                full_disdrometer[name] = full_disdrometer[name].mask(full_disdrometer[name] == marker)
        meta["disdrometro"] = disdrometer_products(frame, full_disdrometer, months, start, end)
    if event_column is not None:
        if event_column not in frame or unit_map[event_column] != "mm" or event_column in COUNTERS:
            raise ValueError("El evento requiere un canal de incrementos en mm, sin contador acumulado.")
        meta["evento"] = {"variable": event_column, **rainfall_event(
            frame[event_column], event_threshold, event_hours)}
    return meta, pd.DataFrame(rows), pd.DataFrame(periods), pd.DataFrame(frequencies)


def radar_files(root, start, end):
    """Solo visita los días elegidos; no recorre todo el archivo de red."""
    paths = []
    for day in pd.date_range(start.normalize(), end.normalize(), freq="D"):
        folder = root / f"{day:%Y}" / f"{day:%Y%m}" / f"{day:%Y%m%d}"
        if folder.exists():
            for path in sorted(folder.glob("*.nc")):
                try:
                    hour = pd.to_datetime(path.stem, format="%Y%m%d_%H%M%S")
                except ValueError:
                    continue
                if hour < end and hour + pd.Timedelta(hours=1) > start:
                    paths.append(path)
    return paths


def read_radar(root, start, end, max_files=48):
    from netCDF4 import Dataset, num2date

    paths = radar_files(root, start, end)
    if not paths:
        raise ValueError("No hay archivos de radar en el intervalo elegido.")
    if len(paths) > max_files:
        raise ValueError(f"El intervalo contiene {len(paths)} archivos de radar; el límite es {max_files}. "
                         "Reduzca el periodo o use --max-radar-files. Los percentiles se calculan en memoria.")
    data, timestamps, ranges, units = {}, [], None, {}
    sites = set()
    for path in paths:
        with Dataset(path) as dataset:
            time_var = dataset.variables["time"]
            time = pd.DatetimeIndex([pd.Timestamp(t.isoformat()) for t in num2date(
                time_var[:], time_var.units, calendar=getattr(time_var, "calendar", "standard"),
                only_use_cftime_datetimes=False)])
            mask = select_time(time, start, end)
            if not mask.any():
                continue
            current_ranges = np.asarray(dataset.variables["range"][:])
            if ranges is None:
                ranges = current_ranges
            elif not np.array_equal(ranges, current_ranges):
                raise ValueError(f"La malla de distancias cambia en {path}; analice por separado.")
            sites.add(str(getattr(dataset, "site_name", "")))
            timestamps.extend(time[mask])
            for name in RADAR_FIELDS:
                if name not in dataset.variables:
                    raise ValueError(f"Falta la variable {name} en {path}")
                variable = dataset.variables[name]
                if variable.dimensions != ("time", "range"):
                    raise ValueError(f"Dimensiones inesperadas para {name} en {path}")
                unit = str(getattr(variable, "units", ""))
                if name in units and units[name] != unit:
                    raise ValueError(f"Cambian las unidades de {name} en {path}")
                units[name] = unit
                values = np.ma.asarray(variable[:], dtype=float).filled(np.nan)[mask]
                data.setdefault(name, []).append(values)
    if not timestamps:
        raise ValueError("Los archivos seleccionados no contienen medidas dentro del intervalo.")
    index = pd.DatetimeIndex(timestamps)
    keep = ~index.duplicated(keep="first")
    rows = []
    for name, blocks in data.items():
        values = np.concatenate(blocks)[keep]
        for gate, distance in enumerate(ranges):
            rows.append({"variable": name, "unidad": units[name], "distancia_m": float(distance),
                         **numeric_summary(pd.Series(values[:, gate]))})
    meta = {
        "carpeta": str(root), "archivos": [str(p) for p in paths],
        "inicio": str(index.min()), "fin": str(index.max()), "registros": int(keep.sum()),
        "duplicados_periodo_descartados": int((~keep).sum()), "zona_horaria": "UTC (NetCDF)",
        "site_name_original": sorted(sites), "numero_distancias": len(ranges),
        "nota": "Resumen por distancia al radar, sin mezclar alturas. Estadísticos aritméticos "
                "en las unidades originales, también para dB/dBZ; no representan promedios en escala lineal. "
                "Se respetan las máscaras NetCDF. Sin filtro de calidad o SNR adicional. "
                "Distancia no equivale a altitud sobre el nivel del mar. Se omiten espectros y ML.",
    }
    return meta, pd.DataFrame(rows), pd.DataFrame(), pd.DataFrame()


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not math.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_report(results, output, start=None, end=None):
    output.mkdir(parents=True, exist_ok=True)
    sections, metadata = [], {}
    for name, (meta, summary, monthly, categories) in results.items():
        metadata[name] = meta
        for suffix, table in (("resumen", summary), ("mensual", monthly), ("codigos", categories)):
            if not table.empty:
                table.to_csv(output / f"{name}_{suffix}.csv", index=False, encoding="utf-8-sig")
        info = "".join(f"<dt>{html.escape(str(k))}</dt><dd>{html.escape(str(v))}</dd>"
                       for k, v in meta.items() if k not in {"archivos", "conversiones_no_numericas", "precipitacion", "disdrometro"})
        notices = []
        if meta.get("valores_7999_revisar"):
            notices.append("Aparecen valores 7999 que pueden condicionar las medias y los máximos. "
                           "Se conservan: confirme su significado antes de interpretar los resultados.")
        if meta.get("valores_menos_9_999"):
            notices.append("Aparecen valores −9.999. Se conservan salvo exclusión explícita por variable; "
                           "no intervienen en los productos gráficos del disdrómetro.")
        warning = "".join(f"<p class='notice'>{html.escape(note)}</p>" for note in notices)
        main_table = monthly if not monthly.empty else summary
        precipitation_section = ""
        if "precipitacion" in meta:
            rain = meta["precipitacion"]
            rain_monthly, rain_daily = pd.DataFrame(rain["mensual"]), pd.DataFrame(rain["diaria"])
            if not rain_monthly.empty:
                rain_monthly.to_csv(output / f"{name}_precipitacion_mensual.csv", index=False, encoding="utf-8-sig")
                rain_daily.to_csv(output / f"{name}_precipitacion_diaria.csv", index=False, encoding="utf-8-sig")
                plot_precipitation(rain_monthly, rain_daily, output)
                display_table = rain_monthly.drop(columns=["precipitacion_mensual_mm"]).rename(columns={
                    "mes": "Mes", "precipitacion_observada_mm": "Cantidad observada (mm)",
                    "estado": "Estado", "cobertura_pct": "Cobertura (%)", "dias_completos": "Días completos",
                    "dias_con_precipitacion_completos": "Días completos con precipitación",
                    "media_diaria_dias_completos_mm": "Media diaria (mm; días completos)",
                    "max_diario_dias_completos_mm": "Máximo diario (mm; días completos)",
                    "fecha_max_diario": "Fecha del máximo diario", "intensidad_max_mm_min": "Máximo en 1 min (mm/min)",
                    "fecha_intensidad_max": "Fecha del máximo en 1 min",
                })
                precipitation_section = ("<h3>Precipitación · totalNTR</h3><p>7999 se trata como NaN. "
                    "Las barras rayadas muestran únicamente cantidades observadas en meses incompletos. "
                    "El histograma usa días completos de todo el periodo seleccionado, incluidos los secos.</p>"
                    "<img class='chart' src='precipitacion_mensual.png' alt='Precipitación acumulada mensual'>"
                    "<img class='chart' src='histograma_precipitacion_diaria.png' alt='Histograma de precipitación diaria'>"
                    "<h3>Tabla mensual de precipitación</h3><div class='scroll'>"
                    + display_table.to_html(index=False, na_rep="—", float_format=lambda v: f"{v:.2f}")
                    + "</div><p>" + html.escape(rain["metodo"]) + "</p>")
        if "disdrometro" in meta:
            precipitation_section += write_disdrometer_section(meta["disdrometro"], output)
        sections.append(f"<section><h2>{html.escape(name)}</h2>{warning}<dl>{info}</dl>"
                        + precipitation_section
                        + ("<details><summary>Estadísticos adicionales de los canales</summary>" if precipitation_section else "")
                        + ("<h3>Estadísticos mensuales</h3><p>Cobertura respecto al mes natural completo. "
                           "Los meses incompletos describen únicamente las medidas disponibles.</p>" if not monthly.empty else "")
                        + f"<div class='scroll'>{main_table.to_html(index=False, na_rep='—', float_format=lambda v: f'{v:.5g}')}</div>"
                        + ("<h3>Frecuencias de códigos</h3>" + categories.to_html(index=False, na_rep="Ausente") if not categories.empty else "")
                        + ("</details>" if precipitation_section else "")
                        + "</section>")
    (output / "metadatos.json").write_text(json.dumps(clean_json(metadata), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    document = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hoya de Pedraza · MeteoReport</title>
<style>body{font:16px system-ui;color:#213547;background:#f3f6fa;margin:0;padding:32px}
main{max-width:1400px;margin:auto}h1{color:#125966}section{background:white;padding:24px;margin:24px 0;border-radius:12px}
dl{display:grid;grid-template-columns:minmax(180px,1fr) 3fr;gap:8px}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}
.chart{display:block;width:100%;max-width:1100px;height:auto;margin:20px 0}.scroll{overflow:auto}table{border-collapse:collapse;font-size:14px}th,td{padding:8px;border-bottom:1px solid #dde4eb;text-align:right}
th{background:#e6eff2}p{line-height:1.6}footer{color:#526272}.notice{background:#fff3d6;padding:16px;border-left:4px solid #bd8100}</style><main><h1>Hoya de Pedraza</h1>
<p>MeteoReport · Resumen descriptivo de las medidas registradas.</p>"""
    document += ("<p>Alcance: análisis mensual y, opcionalmente, un único evento candidato de "
                 "al menos 50 mm en 72 horas (umbrales configurables). Sin análisis anual o estacional. "
                 "La búsqueda de eventos solo se activa al indicar un canal confirmado de incrementos de precipitación.</p>")
    start_label = str(start) if start is not None else "sin límite"
    end_label = str(end) if end is not None else "sin límite"
    document += (f"<p>Filtro: inicio inclusivo {html.escape(start_label)}; "
                 f"fin exclusivo {html.escape(end_label)}.</p>")
    document += """<p>Desviación estándar muestral (n−1); percentiles con interpolación lineal.
Los ceros se conservan. Ausentes incluye valores no numéricos e infinitos. Las filas con fecha inválida se descartan;
en marcas temporales repetidas se conserva la primera. Los contadores/niveles no se suman directamente;
la precipitación de meteo se deriva de incrementos válidos de totalNTR. En meteo, 7999 se convierte a NaN.
Los códigos se presentan como frecuencias. El valor −9.999 se conserva salvo exclusión explícita por variable:
su significado debe confirmarse en la documentación del instrumento. No se aplica una validación física automática.</p>
<p>La cobertura TOA5 supone una cadencia de 60 s y solo abarca desde la primera hasta la última medida observada
del periodo. No mide la disponibilidad fuera de ese intervalo ni la validez de cada variable.</p>"""
    document += "".join(sections)
    document += "<footer>Los archivos CSV contienen los resúmenes exportables; metadatos.json conserva la procedencia y las decisiones de lectura.</footer></main></html>"
    (output / "informe.html").write_text(document, encoding="utf-8")
    return output / "informe.html"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Z:/HDP"))
    parser.add_argument("--output", type=Path, default=Path("informes/ultimo"))
    parser.add_argument("--instrument", choices=["superficie", "meteo", "disdrometer", "radar", "todos"], default="superficie")
    parser.add_argument("--start", type=date_arg, help="Inicio inclusivo ISO; hora original TOA5, UTC radar")
    parser.add_argument("--end", type=date_arg, help="Fin exclusivo ISO; hora original TOA5, UTC radar")
    parser.add_argument("--max-radar-files", type=int, default=48)
    parser.add_argument("--rain-increment-column", help="Canal TOA5 confirmado de incrementos en mm por minuto; activa un único evento")
    parser.add_argument("--event-threshold-mm", type=float, default=50)
    parser.add_argument("--event-hours", type=int, default=72)
    parser.add_argument("--exclude", action="append", default=[], metavar="VARIABLE=VALOR", help="Excluir un valor concreto en una variable TOA5; repetible")
    args = parser.parse_args()
    if args.event_threshold_mm <= 0 or not math.isfinite(args.event_threshold_mm) or args.event_hours < 1:
        parser.error("El umbral y la duración del evento deben ser positivos y finitos.")
    if args.rain_increment_column and args.instrument not in {"meteo", "disdrometer"}:
        parser.error("Seleccione --instrument meteo o disdrometer para el canal de evento.")
    if args.start is not None and args.end is not None and args.start >= args.end:
        parser.error("--end debe ser posterior a --start")
    if args.instrument in {"radar", "todos"} and (args.start is None or args.end is None):
        parser.error("El radar requiere --start y --end para limitar la lectura de la unidad de red.")
    exclusions = {}
    for item in args.exclude:
        try:
            name, value = item.split("=", 1)
            exclusions.setdefault(name, []).append(float(value))
        except ValueError:
            parser.error("--exclude debe tener el formato VARIABLE=VALOR")
    results = {}
    try:
        for name in ("meteo", "disdrometer"):
            if args.instrument in {"superficie", "todos", name}:
                path = args.source / "meteo" / f"CR1000XSeries_{name}.dat"
                print(f"Leyendo {path}…", flush=True)
                results[name] = read_toa5(path, args.start, args.end, exclusions,
                                          args.rain_increment_column, args.event_threshold_mm, args.event_hours)
        if args.instrument in {"radar", "todos"}:
            print("Leyendo perfiles del radar…", flush=True)
            results["radar"] = read_radar(args.source / "mrrpro82", args.start, args.end, args.max_radar_files)
        if not any(result[0]["registros"] for result in results.values()):
            raise ValueError("No hay medidas en el intervalo elegido.")
        report = write_report(results, args.output, args.start, args.end)
        print(f"Informe generado: {report.resolve()}")
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
