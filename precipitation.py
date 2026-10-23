"""Precipitación a partir de diferencias consecutivas del contador totalNTR."""
from pathlib import Path

import numpy as np
import pandas as pd


def precipitation_tables(counter, months, start=None, end=None, source="totalNTR"):
    counter = pd.to_numeric(counter, errors="coerce").replace([7999, np.inf, -np.inf], np.nan)
    counter = counter.sort_index(kind="stable")
    counter = counter.loc[~counter.index.duplicated(keep="first")]
    counter = counter.where(counter >= 0)
    difference = counter.diff()
    consecutive = counter.index.to_series().diff() == pd.Timedelta(minutes=1)
    resets = consecutive & (difference < -1e-8)
    increments = difference.where(consecutive & (difference >= -1e-8)).clip(lower=0)
    # Una lectura a las 00:00 cierra el minuto 23:59 del día anterior.
    increments.index = increments.index - pd.Timedelta(minutes=1)
    if start is not None:
        increments = increments.loc[increments.index >= start]
    if end is not None:
        increments = increments.loc[increments.index < end]
    if not len(months):
        return pd.DataFrame(), pd.DataFrame(), {}
    increments = increments.loc[increments.index.to_period("M").isin(months)]
    if not (increments.index == increments.index.floor("min")).all():
        raise ValueError(f"{source} debe tener marcas temporales en minutos exactos.")
    dates = pd.date_range(months[0].start_time, months[-1].end_time.normalize(), freq="D")
    grouped = increments.groupby(increments.index.normalize())
    daily = pd.DataFrame(index=dates)
    daily.index.name = "fecha"
    daily["minutos_validos"] = grouped.count().reindex(dates, fill_value=0)
    daily["cobertura_pct"] = 100 * daily.minutos_validos / 1440
    daily["completo"] = daily.minutos_validos == 1440
    daily["precipitacion_observada_mm"] = grouped.sum(min_count=1).reindex(dates)
    daily["precipitacion_diaria_mm"] = daily.precipitacion_observada_mm.where(daily.completo)
    rows = []
    for month in months:
        block = daily.loc[daily.index.to_period("M") == month]
        valid = int(block.minutos_validos.sum())
        complete_days = block.loc[block.completo, "precipitacion_diaria_mm"]
        complete = valid == month.days_in_month * 1440
        observed = block.precipitacion_observada_mm.sum(min_count=1)
        minute_values = increments.loc[increments.index.to_period("M") == month].dropna()
        rows.append({
            "mes": str(month), "precipitacion_observada_mm": observed,
            "precipitacion_mensual_mm": observed if complete else np.nan,
            "estado": "Completo" if complete else ("Parcial" if valid else "Sin datos válidos"),
            "cobertura_pct": 100 * valid / (month.days_in_month * 1440),
            "dias_completos": len(complete_days),
            "dias_con_precipitacion_completos": int((complete_days > 0).sum()),
            "media_diaria_dias_completos_mm": complete_days.mean(),
            "max_diario_dias_completos_mm": complete_days.max(),
            "fecha_max_diario": str(complete_days.idxmax().date()) if len(complete_days) else None,
            "intensidad_max_mm_min": minute_values.max(),
            "fecha_intensidad_max": str(minute_values.idxmax() + pd.Timedelta(minutes=1)) if len(minute_values) else None,
        })
    quality = {
        "origen": f"{source} (mm)",
        "metodo": "Diferencias no negativas entre lecturas válidas separadas exactamente 60 s. "
                  "7999, infinitos y contadores negativos se tratan como ausentes. "
                  "Las diferencias negativas se consideran reinicios/correcciones y se descartan. "
                  "No se calculan incrementos atravesando huecos o NaN. "
                  "Cada incremento pertenece al minuto que termina en la marca del registro. "
                  f"La intensidad máxima es el mayor incremento de un minuto de {source}, "
                  "con la fecha de su lectura de cierre. "
                  "Los acumulados parciales son cantidades observadas, sin extrapolación. "
                  "El histograma y los máximos diarios solo usan días completos; incluyen días secos.",
        "descensos_contador_consecutivos_archivo": int(resets.sum()),
    }
    return pd.DataFrame(rows), daily.reset_index(), quality


def plot_precipitation(monthly, daily, output, source="totalNTR", prefix="", histogram=True):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    output = Path(output)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    figure, axis = plt.subplots(figsize=(11, 4.8), layout="constrained")
    x = np.arange(len(monthly))
    colors = ["#187c8a" if s == "Completo" else "#e5ab42" for s in monthly.estado]
    bars = axis.bar(x, monthly.precipitacion_observada_mm.fillna(0), color=colors)
    for bar, state in zip(bars, monthly.estado):
        if state == "Parcial":
            bar.set_hatch("///")
    for i, value in enumerate(monthly.precipitacion_observada_mm):
        if pd.notna(value):
            axis.annotate(f"{value:.2f}", (i, value), xytext=(0, 5), textcoords="offset points",
                          ha="center", fontsize=8)
    missing = monthly.precipitacion_observada_mm.isna()
    axis.scatter(x[missing], np.zeros(missing.sum()), marker="x", color="#a33535", zorder=4)
    axis.set_xticks(x, monthly.mes, rotation=45, ha="right")
    axis.set_ylabel("Precipitación (mm = l/m²)")
    axis.set_title(f"Precipitación acumulada por mes · {source}", loc="left", weight="bold")
    maximum = monthly.precipitacion_observada_mm.max()
    axis.set_ylim(0, max(1, maximum * 1.35) if pd.notna(maximum) else 1)
    axis.grid(axis="y", alpha=.2)
    axis.set_axisbelow(True)
    axis.legend(handles=[Patch(color="#187c8a", label="Mes completo"),
                         Patch(facecolor="#e5ab42", hatch="///", label="Mes parcial: solo cantidad observada"),
                         plt.Line2D([], [], marker="x", color="#a33535", linestyle="", label="Sin datos válidos")],
                loc="upper right", fontsize=8)
    figure.savefig(output / f"{prefix}precipitacion_mensual.png", dpi=170)
    plt.close(figure)

    if not histogram:
        return

    values = daily.loc[daily.completo, "precipitacion_diaria_mm"].dropna()
    figure, axis = plt.subplots(figsize=(10, 4.8), layout="constrained")
    if len(values):
        bins = min(20, max(5, int(np.sqrt(len(values)))))
        axis.hist(values, bins=bins, color="#187c8a", edgecolor="white")
        axis.yaxis.get_major_locator().set_params(integer=True)
    else:
        axis.text(.5, .5, "No hay días completos para construir el histograma", ha="center", transform=axis.transAxes)
    axis.set_xlabel("Precipitación diaria (mm = l/m²)")
    axis.set_ylabel("Número de días")
    axis.set_title("Distribución de precipitación diaria · días completos", loc="left", weight="bold")
    axis.text(0, -.22, f"{len(values)} días completos; {(values == 0).sum()} secos. Se excluyen días incompletos y sin datos.",
              transform=axis.transAxes, fontsize=9)
    axis.grid(axis="y", alpha=.2)
    axis.set_axisbelow(True)
    figure.savefig(output / "histograma_precipitacion_diaria.png", dpi=170)
    plt.close(figure)
