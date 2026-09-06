"""
Fase 5 -- Exportacion de figuras (PDF vectorial) y tablas (LaTeX/booktabs)
para el reporte. No recalcula nada: solo lee lo que Fase 2/3 ya dejaron en
data/outputs/ y produce los artefactos que `report/main.tex` incluye.

Correr: `python -m src.export` desde la raiz del repo.
"""

from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUTS = os.path.join(BASE_DIR, "data", "outputs")
FIGURES = os.path.join(BASE_DIR, "report", "figures")
TABLES = os.path.join(BASE_DIR, "report", "tables")

PALETA_DEP = {"LAMBAYEQUE": "#1f77b4", "JUNIN": "#8c564b", "LORETO": "#2ca02c"}


def _envolver_resizebox(tex: str) -> str:
    """Envuelve el tabular en \\resizebox{\\textwidth}{!}{...} para que las
    tablas anchas (muchas columnas, nombres de distrito largos) no se salgan
    del margen de la pagina."""
    return tex.replace(
        "\\begin{tabular}", "\\centering\n\\resizebox{\\textwidth}{!}{%\n\\begin{tabular}"
    ).replace("\\end{tabular}", "\\end{tabular}\n}")


def _fig_cobertura_bandas():
    df = pd.read_csv(os.path.join(OUTPUTS, "cobertura_bandas_departamento.csv"))
    orden_bandas = ["<= 30 min", "<= 60 min", "<= 120 min", "> 120 min", "SIN_RUTA"]
    pivot = df.pivot(index="DEPARTAMENTO", columns="banda", values="pct_poblacion").reindex(columns=orden_bandas)

    fig, ax = plt.subplots(figsize=(6.5, 4))
    pivot.plot(kind="bar", stacked=True, ax=ax,
               color=["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#999999"])
    ax.set_ylabel("% de la población")
    ax.set_xlabel("")
    ax.set_title("Cobertura de acceso vial a salud resolutiva, por departamento")
    ax.legend(title="Banda de tiempo", bbox_to_anchor=(1.02, 1), loc="upper left")
    ax.set_xticklabels(pivot.index, rotation=0)
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "cobertura_bandas.pdf"))
    plt.close(fig)


def _fig_lorenz():
    lorenz = pd.read_csv(os.path.join(OUTPUTS, "lorenz_acceso.csv"))
    gini = pd.read_csv(os.path.join(OUTPUTS, "gini_acceso.csv"))
    gini_global = gini.loc[gini["nivel"] == "3_DEPARTAMENTOS", "gini"].iloc[0]

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(lorenz["pct_poblacion_acumulada"], lorenz["pct_tiempo_acumulado"],
            color="#d73027", lw=2, label=f"Curva de Lorenz (Gini={gini_global:.2f})")
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Igualdad perfecta")
    ax.set_xlabel("% de población acumulada (ordenada por tiempo de acceso)")
    ax.set_ylabel("% de tiempo de acceso acumulado")
    ax.set_title("Desigualdad de acceso a salud resolutiva\n(Lambayeque + Junín + Loreto)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "curva_lorenz.pdf"))
    plt.close(fig)


def _fig_comparacion_modos():
    df = pd.read_csv(os.path.join(OUTPUTS, "comparacion_modos.csv"))
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for dep, color in PALETA_DEP.items():
        sub = df[df["departamento_x"] == dep]["ratio_foot_car"].dropna()
        sub = sub[sub < sub.quantile(0.95)]  # recortar cola larga para legibilidad
        if len(sub):
            ax.hist(sub, bins=30, alpha=0.5, label=dep, color=color, density=True)
    ax.set_xlabel("Ratio tiempo a pie / tiempo en auto (al resolutivo más cercano)")
    ax.set_ylabel("Densidad")
    ax.set_title("¿Cuánto más tarda caminar que manejar? -- por departamento")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(FIGURES, "ratio_pie_auto.pdf"))
    plt.close(fig)


def _tabla_acceso_departamental():
    df = pd.read_csv(os.path.join(OUTPUTS, "acceso_departamental.csv"))
    df = df.rename(columns={
        "DEPARTAMENTO": "Departamento", "poblacion_total": "Población",
        "tiempo_medio_ponderado_min": "Acceso medio ponderado (min)",
        "pct_sin_ruta": "Sin ruta (\\%)", "n_centros_poblados": "Centros poblados (muestra)",
    })
    df["Población"] = df["Población"].round(0).astype(int)
    df["Acceso medio ponderado (min)"] = df["Acceso medio ponderado (min)"].round(1)
    df["Sin ruta (\\%)"] = (df["Sin ruta (\\%)"] * 100).round(1)
    tex = df.to_latex(index=False, float_format="%.1f", column_format="lrrrr",
                       caption="Acceso ponderado por población, por departamento.",
                       label="tab:acceso_departamental", position="H")
    with open(os.path.join(TABLES, "acceso_departamental.tex"), "w", encoding="utf-8") as f:
        f.write(_envolver_resizebox(tex))


def _tabla_brechas_criticas():
    df = pd.read_csv(os.path.join(OUTPUTS, "brechas_criticas.csv")).head(10)
    df = df[["DISTRITO", "DEPARTAMENTO", "tiempo_medio_ponderado_min", "poblacion_total", "pct_sin_ruta"]]
    df.columns = ["Distrito", "Departamento", "Acceso (min)", "Población", "Sin ruta (\\%)"]
    df["Población"] = df["Población"].round(0).astype(int)
    df["Acceso (min)"] = df["Acceso (min)"].round(1)
    df["Sin ruta (\\%)"] = (df["Sin ruta (\\%)"] * 100).round(1)
    tex = df.to_latex(index=False, float_format="%.1f", column_format="llrrr",
                       caption="Los 10 distritos con peor acceso ponderado por población.",
                       label="tab:brechas_criticas", position="H")
    with open(os.path.join(TABLES, "brechas_criticas.tex"), "w", encoding="utf-8") as f:
        f.write(_envolver_resizebox(tex))


def _tabla_detour():
    df = pd.read_csv(os.path.join(OUTPUTS, "reporte_detour_factor.csv"))
    df.columns = ["Departamento", "N pares", "Detour mediana", "Detour media", "Detour p90"]
    tex = df.to_latex(index=False, float_format="%.2f", column_format="lrrrr",
                       caption="Factor de detour (distancia en red / distancia en línea recta), por departamento.",
                       label="tab:detour", position="H")
    with open(os.path.join(TABLES, "detour_factor.tex"), "w", encoding="utf-8") as f:
        f.write(tex)


def main():
    os.makedirs(FIGURES, exist_ok=True)
    os.makedirs(TABLES, exist_ok=True)
    _fig_cobertura_bandas()
    _fig_lorenz()
    _fig_comparacion_modos()
    _tabla_acceso_departamental()
    _tabla_brechas_criticas()
    _tabla_detour()
    print("Figuras y tablas exportadas a report/figures/ y report/tables/")


if __name__ == "__main__":
    main()
