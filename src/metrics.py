"""
Fase 3 -- Construccion de metricas de acceso.

Convencion: cada funcion recibe un DataFrame (con las columnas que declara
en su docstring) y devuelve un DataFrame. Nada de logica de metricas vive en
el dashboard (`app.py`); el dashboard solo llama a estas funciones o lee sus
resultados ya exportados en `data/outputs/`.

Columnas esperadas en el DataFrame de demanda "enriquecido"
(`df_demanda` en las firmas de abajo), producido por Fase 2 + Fase 3:
    DEMAND_ID, UBIGEO, DISTRITO, PROVINCIA, DEPARTAMENTO,
    POBLACION_CP (peso poblacional del centro poblado),
    ES_URBANO (bool),
    time_min_car (tiempo de acceso en auto al resolutivo mas cercano)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BANDAS_MIN = (30, 60, 120)


# ---------------------------------------------------------------------------
# Acceso y cobertura
# ---------------------------------------------------------------------------

def tabla_acceso(df_demanda: pd.DataFrame) -> pd.DataFrame:
    """t_min(i): copia limpia de (DEMAND_ID, time_min_car, POBLACION_CP, ...).
    Los puntos sin ruta (NaN) se mantienen -- se excluyen explicitamente de
    los promedios ponderados, no se imputan con 0 ni se descartan en silencio."""
    cols = ["DEMAND_ID", "UBIGEO", "DISTRITO", "PROVINCIA", "DEPARTAMENTO",
            "POBLACION_CP", "ES_URBANO", "time_min_car"]
    out = df_demanda[cols].copy()
    out["ALCANZABLE"] = out["time_min_car"].notna()
    return out


def bandas_cobertura(df_acceso: pd.DataFrame, bandas=BANDAS_MIN, by: list[str] | None = None) -> pd.DataFrame:
    """Porcentaje de poblacion dentro de cada banda de tiempo (<=30, <=60,
    <=120, >120 min, y sin-ruta). `by` agrupa (ej. ['DEPARTAMENTO'])."""
    df = df_acceso.copy()

    def clasificar(t):
        if pd.isna(t):
            return "SIN_RUTA"
        for b in bandas:
            if t <= b:
                return f"<= {b} min"
        return f"> {bandas[-1]} min"

    df["banda"] = df["time_min_car"].map(clasificar)

    grupo = by if by else []
    tot = df.groupby(grupo)["POBLACION_CP"].sum() if grupo else df["POBLACION_CP"].sum()
    agg = df.groupby(grupo + ["banda"])["POBLACION_CP"].sum().reset_index(name="poblacion")
    if grupo:
        agg["poblacion_total_grupo"] = agg[grupo].apply(
            lambda r: tot.loc[tuple(r)] if len(grupo) > 1 else tot.loc[r.iloc[0]], axis=1
        )
    else:
        agg["poblacion_total_grupo"] = tot
    agg["pct_poblacion"] = agg["poblacion"] / agg["poblacion_total_grupo"]
    return agg


# ---------------------------------------------------------------------------
# Agregacion ponderada por poblacion
# ---------------------------------------------------------------------------

def _media_ponderada(valores, pesos):
    valores = np.asarray(valores, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    mask = ~np.isnan(valores) & (pesos > 0)
    if mask.sum() == 0:
        return np.nan
    return float(np.average(valores[mask], weights=pesos[mask]))


def acceso_ponderado_por_nivel(df_acceso: pd.DataFrame, nivel: str) -> pd.DataFrame:
    """nivel in {'DISTRITO','PROVINCIA','DEPARTAMENTO'} (columna a agregar,
    identificada tambien por UBIGEO cuando nivel='DISTRITO').
    Devuelve: nivel, poblacion_total, tiempo_medio_ponderado_min,
    pct_sin_ruta."""
    cols_grupo = ["UBIGEO", nivel] if nivel == "DISTRITO" else [nivel]
    filas = []
    for llave, g in df_acceso.groupby(cols_grupo):
        llave = llave if isinstance(llave, tuple) else (llave,)
        fila = dict(zip(cols_grupo, llave))
        fila["poblacion_total"] = g["POBLACION_CP"].sum()
        fila["tiempo_medio_ponderado_min"] = _media_ponderada(g["time_min_car"], g["POBLACION_CP"])
        fila["pct_sin_ruta"] = 1 - g["ALCANZABLE"].mean() if len(g) else np.nan
        fila["n_centros_poblados"] = len(g)
        filas.append(fila)
    return pd.DataFrame(filas).sort_values("tiempo_medio_ponderado_min", ascending=False).reset_index(drop=True)


def lista_brechas_criticas(df_distrital: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    """Los n distritos con peor acceso ponderado por poblacion (excluye
    distritos con menos de 1 centro poblado con ruta valida)."""
    df = df_distrital.dropna(subset=["tiempo_medio_ponderado_min"])
    return df.sort_values("tiempo_medio_ponderado_min", ascending=False).head(n).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Desigualdad: Gini ponderado por poblacion
# ---------------------------------------------------------------------------

def gini_ponderado(valores, pesos) -> float:
    """Coeficiente de Gini del tiempo de acceso, ponderado por poblacion.

    Se elige Gini (en vez de, p.ej., el rango o la desviacion estandar)
    porque: (1) esta acotado en [0,1] y es directamente interpretable como
    '% de desigualdad maxima posible'; (2) es el estandar en economia de la
    salud para medir inequidad de acceso (usado por OMS/OPS en estudios de
    accesibilidad); y (3) se pondera naturalmente por poblacion sin necesitar
    transformar la variable.
    """
    valores = np.asarray(valores, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    mask = ~np.isnan(valores) & (pesos > 0)
    valores, pesos = valores[mask], pesos[mask]
    if len(valores) == 0:
        return np.nan

    orden = np.argsort(valores)
    valores, pesos = valores[orden], pesos[orden]
    pesos_acum = np.cumsum(pesos)
    pob_total = pesos_acum[-1]
    # Formula de Gini ponderado (curva de Lorenz discreta)
    lorenz = np.cumsum(valores * pesos)
    lorenz = np.insert(lorenz, 0, 0) / lorenz[-1]
    pesos_acum = np.insert(pesos_acum, 0, 0) / pob_total
    b = np.sum((pesos_acum[1:] - pesos_acum[:-1]) * (lorenz[1:] + lorenz[:-1]))
    return float(1 - b)


def curva_lorenz(valores, pesos) -> pd.DataFrame:
    """Puntos (pct_poblacion_acumulada, pct_tiempo_acumulado) para graficar
    la curva de Lorenz del tiempo de acceso."""
    valores = np.asarray(valores, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    mask = ~np.isnan(valores) & (pesos > 0)
    valores, pesos = valores[mask], pesos[mask]
    orden = np.argsort(valores)
    valores, pesos = valores[orden], pesos[orden]
    pob_acum = np.cumsum(pesos) / pesos.sum()
    tiempo_acum = np.cumsum(valores * pesos) / np.sum(valores * pesos)
    return pd.DataFrame({
        "pct_poblacion_acumulada": np.insert(pob_acum, 0, 0),
        "pct_tiempo_acumulado": np.insert(tiempo_acum, 0, 0),
    })


# ---------------------------------------------------------------------------
# Urbano vs. rural
# ---------------------------------------------------------------------------

def contraste_urbano_rural(df_acceso: pd.DataFrame) -> pd.DataFrame:
    """Regla de clasificacion (declarada explicitamente):
    'urbano' = el centro poblado es capital de distrito, provincia o
    departamento (columna CAPITAL != 0 en el shapefile SIGMED/MINEDU);
    todo lo demas es 'rural'. Es una regla administrativa, no de densidad
    poblacional real -- ver limitaciones en el reporte."""
    filas = []
    for es_urbano, g in df_acceso.groupby("ES_URBANO"):
        filas.append({
            "clase": "urbano" if es_urbano else "rural",
            "n_centros_poblados": len(g),
            "poblacion_total": g["POBLACION_CP"].sum(),
            "tiempo_medio_ponderado_min": _media_ponderada(g["time_min_car"], g["POBLACION_CP"]),
            "pct_sin_ruta": 1 - g["ALCANZABLE"].mean(),
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Cross-analysis: acceso vs. densidad poblacional distrital
# ---------------------------------------------------------------------------

def cruce_acceso_densidad(df_distrital: pd.DataFrame, df_superficie: pd.DataFrame) -> pd.DataFrame:
    """Cruza el acceso ponderado por distrito con la densidad poblacional
    (Poblacion / Superficie_km2, INEI) del mismo distrito.

    `df_superficie` debe tener columnas UBIGEO, Poblacion, Superficie.

    Devuelve el distrital enriquecido + la correlacion de Pearson entre
    tiempo_medio_ponderado_min y densidad (log) como atributo `.attrs['r']`.

    Interpretacion: la densidad poblacional es un PROXY de ruralidad y
    aislamiento geografico (terreno, inversion vial, dispersion de
    poblacion), no una causa directa del tiempo de acceso. La relacion que
    se reporta es correlacional, no causal: ambas variables comparten
    causas comunes (geografia, historia de inversion publica) que este
    analisis no puede aislar.
    """
    sup = df_superficie.rename(columns={"Ubigeo": "UBIGEO"}).copy()
    # Poblacion/Superficie llegan de un CSV externo (INEI) con separador de
    # miles ("4,430.84"); se limpian aqui sin asumir que ya vienen numericas.
    poblacion = pd.to_numeric(sup["Poblacion"].astype(str).str.replace(",", ""), errors="coerce")
    superficie = pd.to_numeric(sup["Superficie"].astype(str).str.replace(",", ""), errors="coerce")
    sup["densidad_hab_km2"] = poblacion / superficie.replace(0, np.nan)
    merged = df_distrital.merge(sup[["UBIGEO", "densidad_hab_km2"]], on="UBIGEO", how="left")

    validos = merged.dropna(subset=["tiempo_medio_ponderado_min", "densidad_hab_km2"])
    if len(validos) >= 3:
        r = float(np.corrcoef(np.log1p(validos["densidad_hab_km2"]), validos["tiempo_medio_ponderado_min"])[0, 1])
    else:
        r = np.nan
    merged.attrs["r_log_densidad_vs_acceso"] = r
    return merged


# ---------------------------------------------------------------------------
# Comparacion entre modos (caminar / auto / bici)
# ---------------------------------------------------------------------------

def comparacion_modos(df_demanda_modos: pd.DataFrame) -> pd.DataFrame:
    """Espera columnas: DEMAND_ID, time_min (auto), time_min_foot, time_min_bike,
    facility_id (auto), facility_id_foot. Calcula ratios y si el
    establecimiento mas cercano cambia entre auto y a pie."""
    df = df_demanda_modos.copy()
    df["ratio_foot_car"] = df["time_min_foot"] / df["time_min"]
    df["ratio_bike_car"] = df["time_min_bike"] / df["time_min"]

    # Comparar como numeros, no como texto: facility_id llega int64 (auto,
    # sin NaN) y facility_id_foot llega float64 (tiene NaN donde no hubo
    # ruta a pie), asi que "27857" vs "27857.0" compararian distinto como
    # string aunque sean el mismo establecimiento. Solo se compara donde
    # AMBOS modos llegaron a algun resolutivo -- si uno no tiene ruta, la
    # pregunta "cambia el establecimiento" no tiene sentido y queda NaN.
    id_car = pd.to_numeric(df["facility_id"], errors="coerce")
    id_foot = pd.to_numeric(df["facility_id_foot"], errors="coerce")
    ambos_ok = id_car.notna() & id_foot.notna()
    df["cambia_establecimiento_auto_vs_pie"] = np.where(
        ambos_ok, id_car != id_foot, np.nan
    )
    return df
