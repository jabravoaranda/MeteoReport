"""Resumen mensual Parsivel2; códigos según manual OTT, apéndice D, página 49."""
from pathlib import Path
import html

import numpy as np
import pandas as pd

from precipitation import plot_precipitation, precipitation_tables


# SYNOP wawa, tabla 4680; no usar la columna ww (4677) del mismo manual.
WAWA = {0: "Sin precipitación", 51: "Llovizna", 52: "Llovizna", 53: "Llovizna",
        57: "Llovizna con lluvia", 58: "Llovizna con lluvia",
        61: "Lluvia", 62: "Lluvia", 63: "Lluvia",
        67: "Lluvia/llovizna con nieve", 68: "Lluvia/llovizna con nieve",
        71: "Nieve", 72: "Nieve", 73: "Nieve", 77: "Nieve granulada",
        87: "Granizo blando", 88: "Granizo blando", 89: "Granizo"}


def operational(frame):
    mask = pd.Series(True, index=frame.index)
    for name in ("sensor_status", "error_code"):
        if name in frame:
            mask &= pd.to_numeric(frame[name], errors="coerce").eq(0)
    return mask


def intensity_box(values, label):
    positive = values.dropna()
    positive = positive.loc[positive > 0]
    if positive.empty:
        return None
    q1, median, q3 = positive.quantile([.25, .5, .75])
    low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
    inside = positive.loc[positive.between(low, high)]
    return {"label": label, "q1": float(q1), "med": float(median), "q3": float(q3),
            "whislo": float(inside.min()), "whishi": float(inside.max()),
            "fliers": positive.loc[~positive.between(low, high)].tolist()}


def disdrometer_products(frame, full_frame, months, start=None, end=None):
    good = operational(frame)
    intensity = frame.rain_intensity.where(good & (frame.rain_intensity >= 0))
    intensity = intensity.replace([np.inf, -np.inf], np.nan)
    full_counter = pd.to_numeric(full_frame.precipitation, errors="coerce").where(operational(full_frame))
    accumulation, daily, quality = precipitation_tables(full_counter, months, start, end, source="precipitation")
    rows, boxes, frequencies = [], [], []
    for month in months:
        selected = frame.index.to_period("M") == month
        values = intensity.loc[selected].dropna()
        positive = values.loc[values > 0]
        rows.append({"mes": str(month), "registros_intensidad_validos": len(values),
                     "cobertura_intensidad_pct": 100 * len(values) / (month.days_in_month * 1440),
                     "n_positivos": len(positive), "n_ceros": int((values == 0).sum()),
                     "porcentaje_positivos": 100 * len(positive) / len(values) if len(values) else np.nan,
                     "mediana_positiva_mm_h": positive.median(), "p95_positivo_mm_h": positive.quantile(.95),
                     "intensidad_max_mm_h": values.max(),
                     "fecha_intensidad_max": str(values.idxmax()) if len(values) else None})
        boxes.append(intensity_box(values, str(month)))
        codes = frame.loc[selected, "weather_code_wawa"].where(good.loc[selected])
        codes = codes.where(codes.between(0, 99) & (codes % 1 == 0)).dropna()
        wet_count = int((codes != 0).sum())
        for code, count in codes.value_counts().sort_index().items():
            frequencies.append({"mes": str(month), "codigo": int(code),
                                "tipo": WAWA.get(int(code), f"No clasificado (código {int(code)})"),
                                "registros": int(count), "horas_equivalentes": int(count) / 60,
                                "pct_codigos_validos": 100 * count / len(codes),
                                "pct_codigos_no_cero": 100 * count / wet_count if code != 0 and wet_count else np.nan})
    monthly = accumulation.drop(columns=["intensidad_max_mm_min", "fecha_intensidad_max"]).merge(pd.DataFrame(rows), on="mes")
    quality.update({
        "intensidad_tabla": "La tabla y el boxplot usan rain_intensity (mm/h), no la intensidad inferida de diferencias del contador.",
        "filtro_calidad": "Para los productos del disdrómetro se requiere sensor_status=0 y error_code=0 "
                          "cuando estos canales existen; ausentes o valores distintos de cero se excluyen. "
                          "Los estadísticos adicionales de canales conservan los datos originales.",
        "registros_excluidos_estado_periodo": int((~good).sum()),
        "boxplot": "rain_intensity > 0, en mm/h. Cuartiles con interpolación lineal; "
                   "bigotes hasta los valores dentro de 1,5 IQR. Los puntos exteriores se conservan. "
                   "Los porcentajes positivos usan como denominador los registros de intensidad válidos, incluidos los ceros. "
                   "No son porcentajes del mes completo ni muestras estadísticamente independientes.",
        "tipos": "SYNOP wawa tabla 4680, manual OTT Parsivel2, apéndice D.1, p. 49. "
                 "Tiempos equivalentes a 60 segundos por registro, sin rellenar huecos; "
                 "la figura omite código 0, conservado en el CSV. Códigos desconocidos se muestran sin reinterpretar.",
        "nota_canales": "rain_intensity corresponde al canal de intensidad equivalente de precipitación; "
                        "no implica exclusivamente lluvia líquida. snow_intensity es intensidad de espesor de nieve "
                        "(equivalente volumétrico); no se suma. −9.999 está dentro del rango declarado de reflectividad "
                        "en el manual, pp. 30 y 37; se conserva en los canales originales y no se utiliza en estas figuras.",
    })
    return {**quality, "mensual": monthly.to_dict("records"),
            "diaria": daily.assign(fecha=daily.fecha.astype(str)).to_dict("records"),
            "boxes": boxes, "tipos_mensuales": frequencies}


def write_disdrometer_section(products, output):
    monthly = pd.DataFrame(products["mensual"])
    daily = pd.DataFrame(products["diaria"])
    types = pd.DataFrame(products["tipos_mensuales"])
    monthly.to_csv(output / "disdrometer_estudio_mensual.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(output / "disdrometer_precipitacion_diaria.csv", index=False, encoding="utf-8-sig")
    types.to_csv(output / "disdrometer_tipos_mensuales.csv", index=False, encoding="utf-8-sig")
    plot_disdrometer(products, output)
    columns = {"mes": "Mes", "precipitacion_observada_mm": "Cantidad observada (mm)",
               "cobertura_pct": "Cobertura acumulado (%)", "dias_completos": "Días completos",
               "cobertura_intensidad_pct": "Cobertura intensidad (%)", "n_positivos": "Registros positivos",
               "porcentaje_positivos": "Positivos / válidos (%)", "mediana_positiva_mm_h": "Mediana positiva (mm/h)",
               "p95_positivo_mm_h": "P95 positivo (mm/h)", "intensidad_max_mm_h": "Máximo (mm/h)",
               "fecha_intensidad_max": "Fecha del máximo"}
    table = monthly[list(columns)].rename(columns=columns)
    notes = "".join(f"<p>{html.escape(products[key])}</p>" for key in
                    ["filtro_calidad", "metodo", "intensidad_tabla", "boxplot", "tipos", "nota_canales"])
    return ("<h3>Disdrómetro · estudio mensual</h3>"
            "<p>Los meses parciales muestran solo cantidades observadas. Los meses sin datos no se interpretan como secos.</p>"
            "<img class='chart' src='disdrometer_precipitacion_mensual.png' alt='Precipitación mensual del disdrómetro'>"
            "<img class='chart' src='disdrometer_boxplot_intensidad.png' alt='Boxplots mensuales de intensidad positiva'>"
            "<img class='chart' src='disdrometer_tipos_precipitacion.png' alt='Tipos de precipitación por mes'>"
            "<h3>Tabla mensual del disdrómetro</h3><div class='scroll'>"
            + table.to_html(index=False, na_rep="—", float_format=lambda v: f"{v:.2f}")
            + "</div><details><summary>Criterios de lectura y cálculo</summary>" + notes + "</details>")


def plot_disdrometer(products, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(output)
    monthly = pd.DataFrame(products["mensual"])
    daily = pd.DataFrame(products["diaria"])
    plot_precipitation(monthly, daily, output, source="Parsivel · precipitation", prefix="disdrometer_", histogram=False)
    figure, axis = plt.subplots(figsize=(12, 6.2))
    figure.subplots_adjust(left=.08, right=.98, top=.90, bottom=.34)
    positions, boxes = zip(*[(i + 1, box) for i, box in enumerate(products["boxes"]) if box]) if any(products["boxes"]) else ([], [])
    if boxes:
        axis.bxp(list(boxes), positions=list(positions), showfliers=True, patch_artist=True,
                 boxprops={"facecolor": "#b8dce1", "edgecolor": "#187c8a"},
                 medianprops={"color": "#943f14", "linewidth": 2},
                 flierprops={"marker": ".", "markersize": 3, "alpha": .45, "markeredgecolor": "#187c8a"})
    else:
        axis.text(.5, .5, "Sin intensidades positivas válidas", ha="center", transform=axis.transAxes)
    labels = []
    for row in monthly.to_dict("records"):
        percentage = f"{row['porcentaje_positivos']:.1f}%" if pd.notna(row["porcentaje_positivos"]) else "sin datos"
        labels.append(f"{row['mes']}\nn={row['n_positivos']}\n{percentage}")
    axis.set_xticks(np.arange(1, len(monthly) + 1), labels, rotation=45, ha="right", fontsize=8)
    axis.set_xlim(.4, len(monthly) + .6)
    axis.set_ylim(bottom=0)
    axis.set_ylabel("rain_intensity positiva (mm/h)")
    axis.set_title("Disdrómetro · intensidad de precipitación por mes", loc="left", weight="bold")
    axis.grid(axis="y", alpha=.2)
    figure.text(.08, .025, "n = registros positivos; % sobre intensidades válidas. Puntos: fuera de 1,5 IQR; se conservan.", fontsize=9)
    figure.savefig(output / "disdrometer_boxplot_intensidad.png", dpi=170)
    plt.close(figure)

    frequencies = pd.DataFrame(products["tipos_mensuales"])
    figure, axis = plt.subplots(figsize=(12, 5.8))
    figure.subplots_adjust(left=.08, right=.74, top=.90, bottom=.23)
    bottom = np.zeros(len(monthly))
    colors = plt.get_cmap("tab10")
    if not frequencies.empty:
        wet = frequencies.loc[frequencies.codigo != 0]
        for i, kind in enumerate(wet.tipo.unique()):
            hours = wet.loc[wet.tipo == kind].groupby("mes").horas_equivalentes.sum().reindex(monthly.mes, fill_value=0).to_numpy()
            axis.bar(np.arange(len(monthly)), hours, bottom=bottom, label=kind, color=colors(i % 10))
            bottom += hours
        if not wet.empty:
            axis.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
    counts = frequencies.groupby("mes").registros.sum() if not frequencies.empty else pd.Series(dtype=int)
    for i, month in enumerate(monthly.mes):
        if counts.get(month, 0) == 0:
            axis.scatter(i, 0, marker="x", color="#a33535", zorder=4)
        elif bottom[i] == 0:
            axis.scatter(i, 0, marker="o", facecolors="none", edgecolors="#666", zorder=4)
    axis.set_xticks(np.arange(len(monthly)), monthly.mes, rotation=45, ha="right")
    axis.set_ylabel("Horas equivalentes observadas (60 s por registro)")
    axis.set_ylim(0, max(1, float(bottom.max()) * 1.12))
    axis.set_title("Disdrómetro · tipos de precipitación registrados", loc="left", weight="bold")
    axis.grid(axis="y", alpha=.2)
    figure.text(.08, .025, "Código 0 omitido. Cruz: sin códigos válidos. Círculo vacío: solo código 0. No se rellenan huecos.", fontsize=9)
    figure.savefig(output / "disdrometer_tipos_precipitacion.png", dpi=170)
    plt.close(figure)
