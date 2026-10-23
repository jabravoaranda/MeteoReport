"""Prueba mensual de distribuciones MRR-PRO en una capa o nivel, en UTC."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from netCDF4 import Dataset, num2date

FIELDS = {"RR": ("Intensidad estimada", "mm/h"), "LWC": ("Agua líquida", "g/m³"),
          "Ze": ("Reflectividad equivalente", "dBZ"), "VEL": ("Velocidad Doppler", "m/s"),
          "WIDTH": ("Anchura espectral", "m/s")}
MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
UNIT_ALIASES = {"RR": {"mm h-1", "mm/h"}, "LWC": {"g m-3", "g/m3"},
                "Ze": {"dBZ"}, "VEL": {"m s-1", "m/s"}, "WIDTH": {"m s-1", "m/s"}}


def month_files(root, month):
    """Admite las dos estructuras de carpetas observadas: AAAA/MM y AAAA/AAAAMM."""
    result = []
    for directory in (root / str(month.year) / f"{month.month:02d}", root / str(month.year) / f"{month.year}{month.month:02d}"):
        if directory.exists():
            for folder, _, files in os.walk(directory):
                result.extend(Path(folder) / name for name in files
                              if name.endswith(".nc") and name.startswith(f"{month.year}{month.month:02d}"))
    return sorted(set(result))


def load_month(root, month, levels, cache_directory, selected_paths=None):
    paths = month_files(root, month) if selected_paths is None else selected_paths
    if not paths:
        raise ValueError(f"No hay archivos para {month}.")
    fingerprint = hashlib.sha256(f"mrr-pilot-v1:{levels}".encode())
    for path in paths:
        info = path.stat()
        fingerprint.update(f"{path}:{info.st_size}:{info.st_mtime_ns}".encode())
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache = cache_directory / f"{month}_{fingerprint.hexdigest()[:20]}.npz"
    if cache.exists():
        with np.load(cache, allow_pickle=False) as stored:
            return stored["times"], stored["values"], json.loads(str(stored["metadata"]))
    times, blocks = [], []
    sites, units, read_paths = set(), {}, []
    for number, path in enumerate(paths, 1):
        with Dataset(path) as dataset:
            coordinate = np.ma.asarray(dataset.variables["range"][:], dtype=float).filled(np.nan)
            if getattr(dataset.variables["range"], "units", "") not in {"m", "meters", "metres"}:
                raise ValueError(f"Unidades desconocidas de range: {path}")
            gates = []
            for level in levels:
                found = np.flatnonzero(np.isclose(coordinate, level, atol=.001, rtol=0))
                if len(found) != 1:
                    raise ValueError(f"El archivo {path} no contiene exactamente el nivel {level:g} m.")
                gates.append(int(found[0]))
            if "elevation" not in dataset.variables or not np.allclose(dataset.variables["elevation"][:], 90, atol=.1):
                raise ValueError(f"No se confirma orientación vertical en {path}.")
            time_var = dataset.variables["time"]
            raw_times = np.ma.asarray(time_var[:], dtype=float).filled(np.nan)
            if not np.isfinite(raw_times).all():
                raise ValueError(f"Marcas temporales no válidas en {path}.")
            if time_var.units == "seconds since 1970-01-01T00:00:00Z":
                dates = pd.DatetimeIndex(pd.to_datetime(raw_times, unit="s"))
            else:
                dates = pd.DatetimeIndex([pd.Timestamp(t.isoformat()) for t in num2date(
                    raw_times, time_var.units, calendar=getattr(time_var, "calendar", "standard"),
                    only_use_cftime_datetimes=False)])
            rounded = dates.round("30s")
            if len(dates) and np.max(np.abs((rounded - dates).total_seconds())) > 2:
                raise ValueError(f"La cadencia nominal de 30 s no es compatible con {path}.")
            keep = rounded.to_period("M") == month
            if not keep.any():
                continue
            data = np.empty((int(keep.sum()), len(levels), len(FIELDS)), dtype=np.float32)
            for column, field in enumerate(FIELDS):
                variable = dataset.variables[field]
                if variable.dimensions != ("time", "range"):
                    raise ValueError(f"Dimensiones inesperadas para {field}: {path}")
                unit = str(getattr(variable, "units", ""))
                if unit not in UNIT_ALIASES[field]:
                    raise ValueError(f"Unidades no compatibles para {field}: {unit!r} en {path}")
                if field in units and units[field] != unit:
                    raise ValueError(f"Cambian las unidades de {field}: {path}")
                units[field] = unit
                # Leer el campo contiguo evita cientos de accesos de red por una columna estriada.
                values = np.ma.asarray(variable[:, :], dtype=np.float32).filled(np.nan)
                data[:, :, column] = values[keep][:, gates]
            times.append(rounded[keep].as_unit("ns").asi8)
            blocks.append(data)
            sites.add(str(getattr(dataset, "site_name", "")))
            read_paths.append(str(path))
        if number % 100 == 0 or number == len(paths):
            print(f"{month}: {number}/{len(paths)} archivos leídos", flush=True)
    if not blocks:
        raise ValueError("Los archivos no contienen registros del mes solicitado.")
    time_array, value_array = np.concatenate(times), np.concatenate(blocks)
    unique = ~pd.Index(time_array).duplicated(keep="first")
    metadata = {"mes": str(month), "niveles_m": levels, "archivos": read_paths,
                "site_name_original": sorted(sites), "unidades_originales": units,
                "duplicados_30s_descartados": int((~unique).sum()), "cadencia_nominal_s": 30}
    time_array, value_array = time_array[unique], value_array[unique]
    np.savez_compressed(cache, times=time_array, values=value_array, metadata=json.dumps(metadata))
    return time_array, value_array, metadata


def level_summary(times, values, month, levels, selected_level):
    layer = isinstance(selected_level, (tuple, list))
    gates = [i for i, level in enumerate(levels) if selected_level[0] <= level <= selected_level[1]] if layer else [levels.index(selected_level)]
    selected = values[:, gates, :].astype(float)
    selected[~np.isfinite(selected)] = np.nan
    # Las distribuciones requieren Ze disponible; RR/LWC=0 sin Ze no se interpretan como medición útil.
    echo = np.isfinite(selected[:, :, list(FIELDS).index("Ze")])
    rows, boxes = [], []
    expected = month.days_in_month * 24 * 120
    dates = pd.to_datetime(times, unit="ns")
    for column, field in enumerate(FIELDS):
        raw = selected[:, :, column]
        mask = echo & np.isfinite(raw)
        if field in {"RR", "LWC", "WIDTH"}:
            mask &= raw >= 0
        counts = mask.sum(axis=1)
        usable = counts > 0
        medians = np.full(len(times), np.nan)
        medians[usable] = np.nanmedian(np.where(mask, raw, np.nan)[usable], axis=1)
        series = pd.Series(medians[usable], index=dates[usable])
        # intensity_box solo acepta positivos; para radar también son válidos ceros y Ze/VEL negativos.
        box = radar_box(series, field)
        boxes.append(box)
        rows.append({"mes": str(month), "referencia_m": reference_label(selected_level), "variable": field,
                     "unidad": FIELDS[field][1], "registros_presentes": len(times),
                     "registros_numericos_originales": int(np.isfinite(raw).any(axis=1).sum()),
                     "niveles_disponibles": len(gates),
                     "mediana_niveles_contribuyentes": float(np.median(counts[usable])) if usable.any() else np.nan,
                     "registros_usados": len(series), "esperados_mes_30s": expected,
                     "cobertura_temporal_pct": 100 * len(times) / expected,
                     "cobertura_valida_pct": 100 * len(series) / expected,
                     "media": series.mean(), "desv_est": series.std(ddof=1),
                     "min": series.min(), "p25": series.quantile(.25), "mediana": series.median(),
                     "p75": series.quantile(.75), "p95": series.quantile(.95), "max": series.max()})
    return pd.DataFrame(rows), boxes


def reference_label(selection):
    return f"{selection[0]:g}-{selection[1]:g} m (mediana vertical)" if isinstance(selection, (tuple, list)) else f"{selection:g} m"


def radar_box(series, label):
    values = series.dropna()
    if values.empty:
        return None
    q1, median, q3 = values.quantile([.25, .5, .75])
    inside = values.between(q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1))
    return {"label": label, "n": len(values), "q1": q1, "med": median, "q3": q3,
            "whislo": values[inside].min(), "whishi": values[inside].max(),
            "fliers": values[~inside].tolist()}


def plot_month(boxes, month, selected_level, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(5, 1, figsize=(11, 13))
    figure.subplots_adjust(left=.12, right=.97, top=.92, bottom=.08, hspace=.75)
    for axis, ((field, (name, unit)), box) in zip(axes, zip(FIELDS.items(), boxes)):
        for m in range(1, 13):
            if m != month.month:
                axis.axvspan(m - .45, m + .45, color="#eeeeee", zorder=0)
        if box is not None:
            axis.bxp([box], positions=[month.month], patch_artist=True, showfliers=True,
                     boxprops={"facecolor": "#b8dce1", "edgecolor": "#187c8a"},
                     medianprops={"color": "#943f14", "linewidth": 2},
                     flierprops={"marker": ".", "markersize": 3, "alpha": .45})
        else:
            axis.text(month.month, .5, "Sin valores\nutilizables", ha="center", va="center",
                      transform=axis.get_xaxis_transform(), fontsize=9, color="#a33535")
        tick_labels = [f"{name}\nn={box['n'] if box else 0}" if number == month.month else name
                       for number, name in enumerate(MONTH_NAMES, 1)]
        axis.set_xticks(range(1, 13), tick_labels)
        axis.set_xlim(.4, 12.6)
        axis.set_ylabel(unit)
        scale = ""
        if field in {"RR", "LWC", "WIDTH"}:
            threshold = {"RR": .01, "LWC": .001, "WIDTH": .01}[field]
            axis.set_yscale("symlog", linthresh=threshold)
            maximum = max([box["whishi"], *box["fliers"]]) if box else threshold
            axis.set_ylim(0, max(threshold * 10, maximum * 1.7))
            scale = f" · escala log, lineal entre 0 y {threshold:g}"
        axis.set_title(f"{field} · {name}{scale}", loc="left", fontsize=11)
        axis.grid(axis="y", alpha=.2)
    figure.suptitle(f"MRR-PRO · {month.year} · {reference_label(selected_level)} sobre el instrumento\n"
                     f"Prueba: {MONTH_NAMES[month.month - 1]} {month.year}; meses grises aún no analizados", fontsize=14)
    figure.text(.12, .025, "Mediana vertical por instante; ≥1 nivel válido. Cajas: Q1–Q3; línea: mediana; bigotes: 1,5 IQR. Extremos conservados. UTC.", fontsize=9)
    tag = reference_label(selected_level).split(" m")[0]
    path = output / f"mrrpro_boxplots_{month.year}_{tag}m.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path


def prepared_path(root, month, selected_level, cache_directory):
    identity = f"v1|{os.path.normcase(os.path.abspath(root))}|{reference_label(selected_level)}"
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return cache_directory / f"prepared_{month}_{key}.npz"


def save_prepared(root, month, selected_level, cache_directory, times, values, metadata):
    cache_directory.mkdir(parents=True, exist_ok=True)
    path = prepared_path(root, month, selected_level, cache_directory)
    metadata = {**metadata, "prepared_schema": 1, "field_order": list(FIELDS),
                "requested_reference": reference_label(selected_level)}
    temporary = path.with_suffix(".tmp.npz")
    np.savez_compressed(temporary, times=times, values=values, metadata=json.dumps(metadata))
    temporary.replace(path)
    return path


def load_prepared(root, month, selected_level, cache_directory):
    path = prepared_path(root, month, selected_level, cache_directory)
    if not path.is_file():
        raise ValueError(f"No hay datos preparados para {month} y {reference_label(selected_level)}. "
                         "Ejecute primero --prepare-only.")
    with np.load(path, allow_pickle=False) as stored:
        metadata = json.loads(str(stored["metadata"]))
        if metadata.get("prepared_schema") != 1 or metadata.get("field_order") != list(FIELDS) or metadata.get("mes") != str(month):
            raise ValueError("Formato de datos preparados incompatible; vuelva a preparar el mes.")
        return stored["times"], stored["values"], metadata


def prepare_month(root, month, selected_level, cache_directory, workers=4):
    paths = month_files(root, month)
    if not paths:
        raise ValueError(f"No hay archivos para {month}.")
    if isinstance(selected_level, (tuple, list)):
        with Dataset(paths[0]) as dataset:
            coordinate = np.asarray(dataset.variables["range"][:])
            levels = [float(v) for v in coordinate if selected_level[0] <= v <= selected_level[1]]
        if not levels:
            raise ValueError("El rango solicitado no contiene niveles.")
        levels = sorted(set(levels + [640., 675.]))
    else:
        levels = sorted(set([float(selected_level), 640., 675.]))
    if workers == 1:
        times, values, metadata = load_month(root, month, levels, cache_directory)
    else:
        chunks = [list(part) for part in np.array_split(paths, min(workers, len(paths))) if len(part)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(load_month, root, month, levels, cache_directory, chunk) for chunk in chunks]
            parts = [future.result() for future in futures]
        times = np.concatenate([part[0] for part in parts])
        values = np.concatenate([part[1] for part in parts])
        unique = ~pd.Index(times).duplicated(keep="first")
        metadata = dict(parts[0][2])
        if any(part[2]["unidades_originales"] != metadata["unidades_originales"] for part in parts):
            raise ValueError("Cambian las unidades entre grupos de archivos.")
        metadata["archivos"] = [path for part in parts for path in part[2]["archivos"]]
        metadata["site_name_original"] = sorted({name for part in parts for name in part[2]["site_name_original"]})
        metadata["duplicados_30s_descartados"] = sum(part[2]["duplicados_30s_descartados"] for part in parts) + int((~unique).sum())
        times, values = times[unique], values[unique]
    for field, unit in metadata["unidades_originales"].items():
        if unit not in UNIT_ALIASES[field]:
            raise ValueError(f"Unidades no compatibles para {field}: {unit!r}")
    save_prepared(root, month, selected_level, cache_directory, times, values, metadata)
    return times, values, metadata


def build_report(root, month, selected_level, output, workers=4, cache_directory=None,
                 prepare_only=False, figures_only=False):
    if prepare_only and figures_only:
        raise ValueError("Seleccione solo una fase.")
    cache_directory = cache_directory or output / "cache"
    if figures_only:
        # Solo disco local; no listar, abrir ni comprobar originales en la unidad de red.
        times, values, metadata = load_prepared(root, month, selected_level, cache_directory)
    else:
        times, values, metadata = prepare_month(root, month, selected_level, cache_directory, workers)
    if prepare_only:
        return prepared_path(root, month, selected_level, cache_directory)
    levels = metadata["niveles_m"]
    output.mkdir(parents=True, exist_ok=True)
    table, boxes = level_summary(times, values, month, levels, selected_level)
    reference = []
    for gate, level in enumerate(levels):
        reference.append({"nivel_m": level, "registros": len(times),
                          "Ze_disponible": int(np.isfinite(values[:, gate, 2]).sum()),
                          "RR_positivo": int((values[:, gate, 0] > 0).sum())})
    availability = pd.DataFrame(reference)
    table.to_csv(output / "mrrpro_mensual.csv", index=False, encoding="utf-8-sig")
    availability.to_csv(output / "mrrpro_comprobacion_niveles.csv", index=False, encoding="utf-8-sig")
    figure = plot_month(boxes, month, selected_level, output)
    metadata.update({"referencia": reference_label(selected_level), "registros_mes": len(times),
                     "agregacion_vertical": "Mediana por instante de las celdas válidas dentro del rango, mínimo un nivel. "
                                            "Después se calcula la distribución mensual de esas medianas. Sin interpolación.",
                     "escalas_figura": "RR, LWC y WIDTH usan escala symlog: tramo lineal cerca de cero "
                                       "hasta 0.01 mm/h, 0.001 g/m³ y 0.01 m/s, respectivamente; "
                                       "Ze y VEL usan escala lineal. Cuartiles y bigotes se calculan en las unidades originales.",
                     "criterio": "Solo Ze disponible y dato propio válido; RR/LWC/WIDTH no negativos. "
                                 "Se conservan los ceros cuando hay Ze disponible. Sin umbral SNR adicional. "
                                 "NetCDF aplica máscaras de origen. Se redondea al intervalo de 30 s "
                                 "con tolerancia de 2 s, conservando la primera muestra de cada intervalo. "
                                 "Coberturas respecto al mes natural completo en UTC.",
                     "interpretacion": "RR y LWC corresponden al procesamiento de fase líquida; "
                                       "VEL es movimiento radial de hidrometeoros, no viento vertical directo. "
                                       "Los niveles se comprueban por separado; no se sustituyen automáticamente.",
                     "niveles_comprobados": reference})
    (output / "metadatos.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    warnings = ""
    if table.registros_usados.max() == 0:
        warnings = ("<p class='notice'>La referencia solicitada no tiene valores utilizables este mes. "
                    "Los ceros de RR/LWC sin Ze disponible no se representan como ausencia real de precipitación. "
                    "Consulte la comprobación de niveles; no se ha cambiado la referencia.</p>")
    display_columns = {"variable": "Variable", "unidad": "Unidad", "registros_usados": "Registros usados",
                       "cobertura_valida_pct": "Cobertura válida (%)", "mediana_niveles_contribuyentes": "Niveles por mediana (mediana)",
                       "mediana": "Mediana", "p25": "P25", "p75": "P75", "p95": "P95", "max": "Máximo"}
    display = table[list(display_columns)].rename(columns=display_columns)
    content = f"""<!doctype html><html lang='es'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MRR-PRO · {month} · {reference_label(selected_level)}</title><style>
body{{font:16px system-ui;background:#f3f6fa;color:#213547;padding:28px}}main{{max-width:1200px;margin:auto}}
section{{background:white;padding:24px;border-radius:12px;margin:20px 0}}img{{width:100%;height:auto}}
table{{border-collapse:collapse;font-size:13px}}th,td{{padding:8px;border-bottom:1px solid #dde4eb;text-align:right}}
.scroll{{overflow:auto}}.notice{{padding:16px;background:#fff3d6;border-left:4px solid #bd8100}}p{{line-height:1.6}}</style>
<main><h1>MRR-PRO · distribuciones mensuales</h1><p>Prueba para {month}, referencia {reference_label(selected_level)} sobre el instrumento.
Los otros meses todavía no se han analizado. Cobertura temporal del mes: {table.cobertura_temporal_pct.iloc[0]:.1f}%.</p>{warnings}
<section><img src='{figure.name}' alt='Cinco paneles de distribuciones mensuales de RR, LWC, Ze, VEL y WIDTH'></section>
<section><h2>Tabla mensual de medianas verticales</h2><div class='scroll'>{display.to_html(index=False, na_rep='—', float_format=lambda v: f'{v:.3g}')}</div>
<p>La cobertura válida requiere Ze y el dato propio disponibles en al menos un nivel. No equivale a frecuencia de precipitación. El CSV conserva todos los estadísticos y recuentos.</p></section>
<section><h2>Comprobación de niveles</h2>{availability.to_html(index=False)}<p>{html.escape(metadata['criterio'])}</p>
<p>{html.escape(metadata['agregacion_vertical'])}</p><p>{html.escape(metadata['escalas_figura'])}</p><p>{html.escape(metadata['interpretacion'])}</p><p>Fuente técnica: <a href='https://metek.de/product/mrr-pro/'>METEK MRR-PRO</a>.</p></section></main></html>"""
    report = output / "informe.html"
    report.write_text(content, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("Z:/HDP/mrrpro82"))
    parser.add_argument("--month", required=True, help="Mes de prueba AAAA-MM")
    reference = parser.add_mutually_exclusive_group()
    reference.add_argument("--height", type=float, help="Nivel exacto de range, en metros")
    reference.add_argument("--layer", type=float, nargs=2, metavar=("MIN_M", "MAX_M"), help="Mediana vertical en el intervalo inclusivo")
    parser.add_argument("--workers", type=int, default=4, help="Procesos de lectura NetCDF independientes")
    parser.add_argument("--output", type=Path, default=Path("informes/mrrpro_prueba"))
    parser.add_argument("--cache-dir", type=Path, help="Caché reutilizable entre carpetas de informes")
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--prepare-only", action="store_true", help="Leer y guardar datos; no crear figuras")
    phase.add_argument("--figures-only", action="store_true", help="Crear figuras desde datos preparados, sin acceder a Z:")
    args = parser.parse_args()
    try:
        month = pd.Period(args.month, freq="M")
        selected = tuple(args.layer) if args.layer else (args.height if args.height is not None else (640., 840.))
        check = selected if isinstance(selected, tuple) else [selected]
        if not all(np.isfinite(v) and v > 0 for v in check) or (isinstance(selected, tuple) and selected[0] >= selected[1]):
            raise ValueError("La referencia debe ser positiva, finita y creciente.")
        if not 1 <= args.workers <= 8:
            raise ValueError("Use entre 1 y 8 procesos de lectura.")
        print(build_report(args.source, month, selected, args.output, args.workers, args.cache_dir,
                           args.prepare_only, args.figures_only).resolve(), flush=True)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
