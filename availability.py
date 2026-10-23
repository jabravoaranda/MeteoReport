"""Genera la disponibilidad común desde resultados mensuales ya preparados."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import pandas as pd


PRODUCTS = (
    ("pluviometro", "Pluviómetro · acumulado"),
    ("parsivel_acumulado", "Parsivel2 · acumulado"),
    ("parsivel_intensidad", "Parsivel2 · intensidad"),
    ("mrr_temporal", "MRR-PRO · perfiles presentes"),
    ("mrr_RR", "MRR-PRO · RR válido"),
    ("mrr_LWC", "MRR-PRO · LWC válido"),
    ("mrr_Ze", "MRR-PRO · Ze válido"),
    ("mrr_VEL", "MRR-PRO · VEL válido"),
    ("mrr_WIDTH", "MRR-PRO · WIDTH válido"),
)
MRR_FIELDS = ("RR", "LWC", "Ze", "VEL", "WIDTH")


def month_range(first: str, last: str) -> pd.PeriodIndex:
    try:
        start = pd.Period(first, freq="M")
        end = pd.Period(last, freq="M")
    except ValueError as error:
        raise ValueError("Los meses deben tener el formato AAAA-MM.") from error
    if str(start) != first or str(end) != last:
        raise ValueError("Los meses deben tener el formato AAAA-MM.")
    if start > end:
        raise ValueError("El mes inicial debe ser anterior o igual al final.")
    return pd.period_range(start, end, freq="M")


def read_csv(path: Path, required: set[str]) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    table = pd.read_csv(path, encoding="utf-8-sig")
    missing = required - set(table.columns)
    if missing:
        raise ValueError(f"Faltan columnas en {path}: {', '.join(sorted(missing))}")
    return table


def select_month(table: pd.DataFrame, month: str, path: Path) -> pd.DataFrame:
    selected = table.loc[table["mes"].astype(str) == month]
    if selected.empty:
        raise ValueError(f"{path} no contiene el mes {month}.")
    return selected


def collect_availability(reports: Path, months: pd.PeriodIndex) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for period in months:
        month = str(period)
        values = {key: np.nan for key, _ in PRODUCTS}

        meteo_path = reports / "meteo" / month / "meteo_precipitacion_mensual.csv"
        meteo = read_csv(meteo_path, {"mes", "cobertura_pct"})
        if meteo is not None:
            row = select_month(meteo, month, meteo_path).iloc[0]
            values["pluviometro"] = row["cobertura_pct"]

        parsivel_path = reports / "disdrometer" / month / "disdrometer_estudio_mensual.csv"
        parsivel = read_csv(parsivel_path, {"mes", "cobertura_pct", "cobertura_intensidad_pct"})
        if parsivel is not None:
            row = select_month(parsivel, month, parsivel_path).iloc[0]
            values["parsivel_acumulado"] = row["cobertura_pct"]
            values["parsivel_intensidad"] = row["cobertura_intensidad_pct"]

        mrr_path = reports / "mrrpro" / month / "mrrpro_mensual.csv"
        mrr = read_csv(mrr_path, {"mes", "variable", "cobertura_temporal_pct", "cobertura_valida_pct"})
        if mrr is not None:
            selected = select_month(mrr, month, mrr_path).set_index("variable")
            missing_fields = set(MRR_FIELDS) - set(selected.index)
            if missing_fields:
                raise ValueError(f"Faltan variables en {mrr_path}: {', '.join(sorted(missing_fields))}")
            values["mrr_temporal"] = selected.loc[list(MRR_FIELDS), "cobertura_temporal_pct"].iloc[0]
            for field in MRR_FIELDS:
                values[f"mrr_{field}"] = selected.loc[field, "cobertura_valida_pct"]

        for key, label in PRODUCTS:
            value = pd.to_numeric(pd.Series([values[key]]), errors="coerce").iloc[0]
            if pd.notna(value) and not 0 <= float(value) <= 100:
                raise ValueError(f"Cobertura fuera de 0--100 para {month}, {label}: {value}")
            rows.append({"mes": month, "producto": key, "etiqueta": label,
                         "cobertura_pct": float(value) if pd.notna(value) else np.nan})
    return pd.DataFrame(rows)


def plot_calendar(availability: pd.DataFrame, months: pd.PeriodIndex, path: Path) -> None:
    keys = [key for key, _ in PRODUCTS]
    labels = [label for _, label in PRODUCTS]
    pivot = availability.pivot(index="producto", columns="mes", values="cobertura_pct")
    matrix = pivot.reindex(index=keys, columns=[str(month) for month in months]).to_numpy(dtype=float)
    masked = np.ma.masked_invalid(matrix)
    colormap = plt.colormaps["viridis"].with_extremes(bad="#d9dde2")

    width = max(9.5, 0.78 * len(months) + 4.2)
    figure, axis = plt.subplots(figsize=(width, 6.2), layout="constrained")
    image = axis.imshow(masked, aspect="auto", vmin=0, vmax=100, cmap=colormap)
    axis.set_xticks(range(len(months)), [str(month) for month in months], rotation=45, ha="right")
    axis.set_yticks(range(len(labels)), labels)
    axis.set_title(f"Disponibilidad mensual · {months[0]} a {months[-1]}", loc="left", weight="bold")
    axis.set_xlabel("Mes")

    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            value = matrix[row, column]
            text = "—" if np.isnan(value) else f"{value:.0f}"
            color = "white" if np.isfinite(value) and value >= 55 else "#1f2933"
            axis.text(column, row, text, ha="center", va="center", color=color, fontsize=8)

    colorbar = figure.colorbar(image, ax=axis, pad=0.02, shrink=0.86)
    colorbar.set_label("Cobertura válida (%)")
    axis.legend(handles=[Patch(facecolor="#d9dde2", edgecolor="#9ca3af",
                               label="Sin resultado preparado")],
                loc="upper center", bbox_to_anchor=(0.5, -0.22), frameon=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(figure)


def latex_number(value: float) -> str:
    if pd.isna(value):
        return "---"
    return f"{value:.1f}".replace(".", ",")


def write_latex_table(availability: pd.DataFrame, months: pd.PeriodIndex, path: Path) -> None:
    pivot = availability.pivot(index="mes", columns="producto", values="cobertura_pct")
    columns = [key for key, _ in PRODUCTS]
    lines = [
        "% Generado automáticamente por availability.py; no editar a mano.",
        "\\resizebox{\\textwidth}{!}{%",
        "\\begin{tabular}{@{}lrrrrrrrrr@{}}",
        "\\toprule",
        "Mes & Pluv. & Pars. acum. & Pars. intens. & MRR temp. & RR & LWC & Ze & VEL & WIDTH \\\\",
        "\\midrule",
    ]
    for month in months:
        key = str(month)
        values = [latex_number(pivot.loc[key, column]) for column in columns]
        lines.append(f"{key} & " + " & ".join(values) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}%", "}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def generate(reports: Path, document: Path, first: str, last: str) -> tuple[Path, Path]:
    months = month_range(first, last)
    availability = collect_availability(reports, months)
    figure = document / "figuras" / "calendario_disponibilidad.png"
    table = document / "tablas" / "disponibilidad_mensual.tex"
    plot_calendar(availability, months, figure)
    write_latex_table(availability, months, table)
    return figure, table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-month", required=True, help="Primer mes incluido (AAAA-MM)")
    parser.add_argument("--to-month", required=True, help="Último mes incluido (AAAA-MM)")
    parser.add_argument("--reports", type=Path, default=Path("informes"),
                        help="Carpeta de resultados mensuales ya generados")
    parser.add_argument("--document", type=Path, default=Path("docs/informe_2026"),
                        help="Proyecto LaTeX que recibe figuras/ y tablas/")
    args = parser.parse_args()
    try:
        figure, table = generate(args.reports, args.document, args.from_month, args.to_month)
    except (OSError, ValueError, KeyError, pd.errors.ParserError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Figura: {figure.resolve()}")
    print(f"Tabla: {table.resolve()}")


if __name__ == "__main__":
    main()
