"""
Fase 4 -- Dashboard Streamlit "Golden Hour".

Lee EXCLUSIVAMENTE archivos precomputados de data/processed/ y
data/outputs/ -- no llama a ningun motor de ruteo ni reconstruye grafos al
cargar. Correr con:

    streamlit run app.py
"""

import os

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from src import metrics as M

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED = os.path.join(BASE_DIR, "data", "processed")
OUTPUTS = os.path.join(BASE_DIR, "data", "outputs")
BOUNDARIES = os.path.join(BASE_DIR, "data", "raw", "boundaries", "peru_distrital_simple.geojson")

st.set_page_config(page_title="Golden Hour -- Acceso a Salud Resolutiva", layout="wide", page_icon="🏥")

# ---------------------------------------------------------------------------
# Paleta -- categorica validada contra daltonismo (dataviz skill: slots 1-3
# del set de referencia, los unicos 3 que pasan "all-pairs" en ambos modos).
# El acento de marca (rojo oscuro / azul) es solo cromatico de UI, no se usa
# para codificar datos.
# ---------------------------------------------------------------------------

TEMAS = {
    "Oscuro": {
        "bg": "#0e0e10",
        "surface": "#18181b",
        "surface_2": "#222226",
        "sidebar_bg": "#111113",
        "text": "#f5f5f5",
        "text_muted": "#a3a3a8",
        "border": "#2e2e33",
        "accent": "#a3312b",       # rojo medio oscuro (siempre con texto blanco encima)
        "accent_text": "#ffffff",
        "plotly_template": "plotly_dark",
        "map_style": "carto-darkmatter",
        "seq_scale": "Reds",
        "cat": {"LAMBAYEQUE": "#3987e5", "JUNIN": "#d95926", "LORETO": "#199e70"},
        "cat_bin": {True: "#3987e5", False: "#6b6b70"},
        "resolutivo": {True: "#e66767", False: "#6b6b70"},
    },
    "Claro": {
        "bg": "#f7f8fa",
        "surface": "#ffffff",
        "surface_2": "#eef1f5",
        "sidebar_bg": "#ffffff",
        "text": "#16181d",
        "text_muted": "#5b5f6a",
        "border": "#dde1e7",
        "accent": "#1a56db",       # azul (siempre con texto blanco encima)
        "accent_text": "#ffffff",
        "plotly_template": "plotly_white",
        "map_style": "carto-positron",
        "seq_scale": "Reds",
        "cat": {"LAMBAYEQUE": "#2a78d6", "JUNIN": "#eb6834", "LORETO": "#1baf7a"},
        "cat_bin": {True: "#2a78d6", False: "#9aa1ad"},
        "resolutivo": {True: "#e34948", False: "#9aa1ad"},
    },
}

if "tema" not in st.session_state:
    st.session_state["tema"] = "Oscuro"

with st.sidebar:
    tema_sel = st.segmented_control(
        "Tema", options=["Oscuro", "Claro"], default=st.session_state["tema"], key="tema",
    )
T = TEMAS[st.session_state["tema"]]

# ---------------------------------------------------------------------------
# CSS -- tipografia Arial ~16px, fondo/tarjetas/pills segun tema. Streamlit no
# soporta cambiar de tema en caliente via config.toml (eso solo se lee al
# arrancar), asi que el toggle se implementa inyectando CSS por session_state.
# ---------------------------------------------------------------------------

st.markdown(f"""
<style>
html, body, [class*="st-"], [data-testid="stMarkdownContainer"] p,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"] {{
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 16px;
}}
/* Los iconos de Streamlit usan una tipografia de iconos (Material Symbols) --
   si se fuerza Arial ahi, el glifo se ve como texto literal ("keyboard_..."). */
[data-testid="stIconMaterial"], [data-icon], .material-icons {{
    font-family: "Material Symbols Rounded" !important;
}}
h1 {{ font-size: 1.9rem !important; }}
h2, [data-testid="stMarkdownContainer"] h2 {{ font-size: 1.35rem !important; }}
h3, [data-testid="stMarkdownContainer"] h3 {{ font-size: 1.1rem !important; }}

[data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
    background-color: {T["bg"]} !important;
    color: {T["text"]};
}}
[data-testid="stHeader"] {{ background-color: transparent !important; }}
[data-testid="stSidebar"] {{
    background-color: {T["sidebar_bg"]} !important;
    border-right: 1px solid {T["border"]};
}}
[data-testid="stSidebar"] * {{ color: {T["text"]} !important; }}

p, span, label, li, div {{ color: {T["text"]}; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: {T["text_muted"]} !important; }}

/* Tarjetas de metrica */
[data-testid="stMetric"] {{
    background-color: {T["surface"]};
    border: 1px solid {T["border"]};
    border-radius: 10px;
    padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{ color: {T["text"]} !important; font-weight: 700; }}
[data-testid="stMetricLabel"] {{
    color: {T["text_muted"]} !important;
    white-space: normal !important;
    overflow: visible !important;
    font-size: 13px !important;
}}
[data-testid="stMetricLabel"] p {{ white-space: normal !important; overflow: visible !important; }}

/* Pills (filtros) y segmented control (tema) -- ambos widgets renderizan
   como [data-testid="stButtonGroup"] > button, seleccionado = aria-pressed */
[data-testid="stButtonGroup"] button {{
    border-radius: 999px !important;
    border: 1px solid {T["border"]} !important;
    background-color: {T["surface_2"]} !important;
    font-size: 14px !important;
    margin: 2px !important;
}}
[data-testid="stButtonGroup"] button p {{ color: {T["text"]} !important; }}
[data-testid="stButtonGroup"] button[aria-pressed="true"],
[data-testid="stButtonGroup"] button[aria-checked="true"],
[data-testid="stButtonGroup"] button[data-selected="true"] {{
    background-color: {T["accent"]} !important;
    border-color: {T["accent"]} !important;
}}
[data-testid="stButtonGroup"] button[aria-pressed="true"] p,
[data-testid="stButtonGroup"] button[aria-checked="true"] p,
[data-testid="stButtonGroup"] button[data-selected="true"] p {{
    color: {T["accent_text"]} !important;
}}

/* Pestañas */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {T["border"]}; }}
.stTabs [data-baseweb="tab"] {{
    background-color: transparent; color: {T["text_muted"]}; font-size: 15px;
}}
.stTabs [aria-selected="true"] {{
    color: {T["accent"]} !important; border-bottom: 2px solid {T["accent"]} !important;
}}

/* Botones y sliders */
.stButton button, .stDownloadButton button {{
    background-color: {T["accent"]}; color: {T["accent_text"]};
    border: none; border-radius: 8px; font-size: 14px;
}}
[data-testid="stSliderThumbValue"], [data-testid="stTickBarMin"], [data-testid="stTickBarMax"] {{
    color: {T["text_muted"]} !important;
}}

hr {{ border-color: {T["border"]}; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Carga de datos (cacheada)
# ---------------------------------------------------------------------------

@st.cache_data
def cargar_datos():
    oferta = gpd.read_parquet(os.path.join(PROCESSED, "establecimientos_salud.parquet"))
    demanda = gpd.read_parquet(os.path.join(PROCESSED, "demanda_muestra.parquet"))
    nearest_car = pd.read_parquet(os.path.join(PROCESSED, "nearest_car.parquet"))
    matriz_car = pd.read_parquet(os.path.join(PROCESSED, "routing_matrix_car.parquet"))
    matriz_candidatos = pd.read_parquet(os.path.join(PROCESSED, "routing_matrix_car_candidatos.parquet"))
    acceso_distrital = pd.read_csv(os.path.join(OUTPUTS, "acceso_distrital.csv"), dtype={"UBIGEO": str})
    calidad = pd.read_csv(os.path.join(OUTPUTS, "reporte_calidad_datos_oferta.csv"))
    snap = pd.read_csv(os.path.join(OUTPUTS, "reporte_snap.csv"))
    distritos = gpd.read_file(BOUNDARIES)
    return oferta, demanda, nearest_car, matriz_car, matriz_candidatos, acceso_distrital, calidad, snap, distritos


try:
    (oferta, demanda, nearest_car, matriz_car, matriz_candidatos,
     acceso_distrital, calidad, snap, distritos) = cargar_datos()
except FileNotFoundError as e:
    st.error(
        "Faltan archivos precomputados de Fase 2/3. Corre primero el pipeline "
        f"(`data/Fase2_Routing.ipynb`, `data/Fase3_Metricas.ipynb`). Detalle: {e}"
    )
    st.stop()

demanda = demanda.merge(nearest_car, on="DEMAND_ID", how="left")


def _fig_tema(fig):
    """Aplica el tema activo a una figura Plotly: fondo transparente (para
    que se funda con el fondo de Streamlit) y tipografia Arial."""
    fig.update_layout(
        template=T["plotly_template"],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, Helvetica, sans-serif", size=13, color=T["text"]),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar -- filtros como listas de "pills" (compactas, sin las etiquetas
# abultadas con "x" del multiselect por defecto).
# ---------------------------------------------------------------------------

st.sidebar.markdown("### Filtros")

departamentos = sorted(demanda["DEP_NORM"].dropna().unique())
f_depto = st.sidebar.pills(
    "Departamento", departamentos, selection_mode="multi", default=departamentos, key="f_depto",
) or []

provincias_disp = sorted(demanda.loc[demanda["DEP_NORM"].isin(f_depto), "PROV"].dropna().unique())
f_prov = st.sidebar.pills(
    "Provincia (opcional)", provincias_disp, selection_mode="multi", default=[], key="f_prov",
) or []

categorias = sorted(oferta["CATEGORIA_NORM"].dropna().unique())
f_cat = st.sidebar.pills(
    "Categoria de establecimiento", categorias, selection_mode="multi", default=categorias, key="f_cat",
) or []

instituciones = sorted(oferta["INSTITUCION"].dropna().unique())
f_inst = st.sidebar.pills(
    "Institucion", instituciones, selection_mode="multi", default=instituciones, key="f_inst",
) or []

f_umbral = st.sidebar.slider("Umbral de tiempo de acceso (min)", 10, 180, 60, step=10)

# ---------------------------------------------------------------------------
# Aplicar filtros (manejo explicito de seleccion vacia)
# ---------------------------------------------------------------------------

dem_f = demanda[demanda["DEP_NORM"].isin(f_depto)] if f_depto else demanda.iloc[0:0]
if f_prov:
    dem_f = dem_f[dem_f["PROV"].isin(f_prov)]

of_f = oferta[oferta["CATEGORIA_NORM"].isin(f_cat) & oferta["INSTITUCION"].isin(f_inst)] if (f_cat and f_inst) else oferta.iloc[0:0]

st.title("🏥 Golden Hour")
st.caption("Acceso vial a salud resolutiva -- Lambayeque (costa) · Junín (sierra) · Loreto (selva) -- ver `config.md`")

if dem_f.empty:
    st.warning("No hay puntos de demanda para la seleccion actual. Ajusta los filtros del sidebar.")
    st.stop()

# ---------------------------------------------------------------------------
# KPI header
# ---------------------------------------------------------------------------

pob_total = dem_f["POBLACION_CP"].sum()
pob_cubierta = dem_f.loc[dem_f["time_min"] <= f_umbral, "POBLACION_CP"].sum()
pob_mas_alla = pob_total - pob_cubierta
mediana_acceso = np.average(
    dem_f["time_min"].dropna(),
    weights=dem_f.loc[dem_f["time_min"].notna(), "POBLACION_CP"],
) if dem_f["time_min"].notna().any() else np.nan

peor_distrito_row = (
    acceso_distrital[acceso_distrital["DEPARTAMENTO"].isin(f_depto)]
    .sort_values("tiempo_medio_ponderado_min", ascending=False)
    .head(1)
)
peor_distrito = (
    f"{peor_distrito_row['DISTRITO'].iloc[0]} ({peor_distrito_row['tiempo_medio_ponderado_min'].iloc[0]:.0f} min)"
    if len(peor_distrito_row) else "N/D"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Poblacion cubierta (≤{f_umbral} min)", f"{pob_cubierta:,.0f}", f"{pob_cubierta/pob_total:.1%}" if pob_total else "N/D")
c2.metric(f"Poblacion mas alla de {f_umbral} min", f"{pob_mas_alla:,.0f}", f"{pob_mas_alla/pob_total:.1%}" if pob_total else "N/D")
c3.metric("Peor distrito (acceso ponderado)", peor_distrito)
c4.metric("Mediana ponderada de acceso", f"{mediana_acceso:.0f} min" if not np.isnan(mediana_acceso) else "N/D")

st.divider()

tabs = st.tabs([
    "🗺️ Mapa", "🏥 Establecimientos", "📊 Distribucion", "📋 Ranking de distritos",
    "🧪 Simulador de escenarios", "✅ Calidad de datos",
])

# ---------------------------------------------------------------------------
# Mapa coropletico
# ---------------------------------------------------------------------------

with tabs[0]:
    st.subheader("Tiempo de acceso ponderado por poblacion, por distrito")
    dist_f = distritos[distritos["NOMBDEP"].isin(f_depto)].merge(
        acceso_distrital[["UBIGEO", "tiempo_medio_ponderado_min", "poblacion_total", "pct_sin_ruta"]],
        left_on="IDDIST", right_on="UBIGEO", how="left",
    )
    if dist_f["tiempo_medio_ponderado_min"].notna().any():
        # Escala secuencial de un solo tono (nunca arcoiris) -- mas claro es
        # mejor acceso, mas oscuro/rojo es peor, coherente en ambos temas.
        fig = px.choropleth_map(
            dist_f, geojson=dist_f.geometry.__geo_interface__, locations=dist_f.index,
            color="tiempo_medio_ponderado_min", hover_name="NOMBDIST",
            hover_data={"poblacion_total": True, "pct_sin_ruta": ":.1%"},
            color_continuous_scale=T["seq_scale"], map_style=T["map_style"],
            center={"lat": dist_f.geometry.centroid.y.mean(), "lon": dist_f.geometry.centroid.x.mean()},
            zoom=5, opacity=0.8, labels={"tiempo_medio_ponderado_min": "Minutos"},
        )
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=550)
        st.plotly_chart(_fig_tema(fig), width="stretch")
    else:
        st.info("Sin datos de acceso distrital para los departamentos seleccionados.")

# ---------------------------------------------------------------------------
# Capa de establecimientos
# ---------------------------------------------------------------------------

with tabs[1]:
    st.subheader("Establecimientos de salud")
    if of_f.empty:
        st.warning("Ninguna categoria/institucion seleccionada.")
    else:
        of_plot = of_f[of_f["DEPARTAMENTO_NORM"].isin(f_depto)]
        fig = px.scatter_map(
            of_plot, lat=of_plot.geometry.y, lon=of_plot.geometry.x,
            color="ES_RESOLUTIVO", hover_name="NOMBRE",
            hover_data=["CATEGORIA_NORM", "INSTITUCION", "ESTADO_NORM"],
            color_discrete_map=T["resolutivo"],
            map_style=T["map_style"], zoom=5, height=550,
        )
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(_fig_tema(fig), width="stretch")
        st.caption(f"{len(of_plot)} establecimientos mostrados · color de acento = resolutivo, gris = no resolutivo")

# ---------------------------------------------------------------------------
# Distribucion
# ---------------------------------------------------------------------------

with tabs[2]:
    st.subheader("Distribucion del tiempo de acceso")
    split = st.radio("Separar por", ["Departamento", "Urbano/Rural"], horizontal=True)
    if split == "Departamento":
        color_col, mapa_color = "DEP_NORM", T["cat"]
    else:
        color_col, mapa_color = "ES_URBANO", T["cat_bin"]

    fig = px.histogram(
        dem_f.dropna(subset=["time_min"]), x="time_min", color=color_col,
        color_discrete_map=mapa_color, barmode="overlay", opacity=0.75, nbins=40,
        labels={"time_min": "Tiempo de acceso (min)", "count": "Centros poblados"},
    )
    fig.update_layout(
        bargap=0.05, height=460,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        xaxis=dict(gridcolor=T["border"]), yaxis=dict(gridcolor=T["border"], title="Centros poblados"),
    )
    st.plotly_chart(_fig_tema(fig), width="stretch")

# ---------------------------------------------------------------------------
# Ranking de distritos
# ---------------------------------------------------------------------------

with tabs[3]:
    st.subheader("Distritos con peor acceso ponderado")
    tabla = acceso_distrital[acceso_distrital["DEPARTAMENTO"].isin(f_depto)].sort_values(
        "tiempo_medio_ponderado_min", ascending=False
    )
    st.dataframe(tabla, width="stretch")
    st.download_button(
        "⬇️ Descargar CSV", tabla.to_csv(index=False).encode("utf-8"),
        file_name="ranking_distritos.csv", mime="text/csv",
    )

# ---------------------------------------------------------------------------
# Simulador de escenarios: upgrade de un I-3/I-4 a resolutivo
# ---------------------------------------------------------------------------

with tabs[4]:
    st.subheader("Simulador: elevar un establecimiento a categoria resolutiva")
    st.caption(
        "Selecciona uno o mas establecimientos I-3/I-4 existentes para simular su "
        "'ascenso' a categoria resolutiva. Se recalcula la cobertura usando la "
        "matriz completa de Fase 2 (sin volver a rutear)."
    )
    candidatos = oferta[
        oferta["CATEGORIA_NORM"].isin(["I-3", "I-4"]) & oferta["DEPARTAMENTO_NORM"].isin(f_depto)
    ]
    seleccion = st.multiselect(
        "Establecimientos a elevar", candidatos["COD_IPRESS"].astype(str),
        format_func=lambda cod: f"{cod} -- " + candidatos.loc[candidatos['COD_IPRESS'].astype(str) == cod, 'NOMBRE'].iloc[0]
        if (candidatos['COD_IPRESS'].astype(str) == cod).any() else cod,
    )

    if seleccion:
        matriz_extra = matriz_candidatos[
            matriz_candidatos["facility_id"].astype(str).isin(seleccion) & matriz_candidatos["routed_ok"]
        ]
        mejor_extra = matriz_extra.groupby("demand_id")["time_min"].min()

        tiempo_actual = dem_f.set_index("DEMAND_ID")["time_min"]
        idx_comun = tiempo_actual.index.intersection(mejor_extra.index)
        tiempo_nuevo = tiempo_actual.copy()
        tiempo_nuevo.loc[idx_comun] = np.minimum(tiempo_actual.loc[idx_comun], mejor_extra.loc[idx_comun])

        pob = dem_f.set_index("DEMAND_ID")["POBLACION_CP"]
        cobertura_antes = pob[tiempo_actual <= f_umbral].sum()
        cobertura_despues = pob[tiempo_nuevo <= f_umbral].sum()
        ganancia = cobertura_despues - cobertura_antes

        c1, c2, c3 = st.columns(3)
        c1.metric(f"Cobertura actual (≤{f_umbral} min)", f"{cobertura_antes:,.0f}")
        c2.metric(f"Cobertura simulada (≤{f_umbral} min)", f"{cobertura_despues:,.0f}")
        c3.metric("Ganancia marginal de poblacion cubierta", f"+{ganancia:,.0f}")
    else:
        st.info("Selecciona al menos un establecimiento para ver el efecto simulado.")

# ---------------------------------------------------------------------------
# Panel de calidad de datos
# ---------------------------------------------------------------------------

with tabs[5]:
    st.subheader("Reporte de calidad de datos (Fase 1)")
    st.dataframe(calidad, width="stretch")
    st.subheader("Reporte de snapping a la red vial (Fase 2)")
    st.dataframe(snap, width="stretch")
