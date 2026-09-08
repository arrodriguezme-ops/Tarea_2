"""
Fase 2 -- Routing y calculo de tiempos de viaje.

Motor elegido: **pyosmium + NetworkX**, no OSRM en Docker.

Por que: Docker no esta disponible en esta maquina, y `pyrosm` (que permite
alimentar OSMnx directamente desde un .osm.pbf local) requiere un compilador
de C++ (Microsoft Visual C++ Build Tools) que tampoco esta instalado. La
alternativa que si funciona sin dependencias nativas pesadas es `pyosmium`
(bindings de libosmium con wheels precompiladas) para leer el .pbf, combinado
con un grafo `networkx` construido a mano. Esto es exactamente la opcion
"OSMnx + NetworkX" que el enunciado ofrece como alternativa aceptable a OSRM,
con la unica diferencia de que la extraccion del grafo desde el .pbf se hace
con pyosmium en vez de con la funcion de descarga de OSMnx (que requeriria
Overpass API en linea, no un archivo local).

Simplificaciones declaradas (ver tambien Fase 5 -- Limitaciones):
  - El grafo se trata como NO dirigido: se ignoran restricciones de sentido
    unico (`oneway`). Para un analisis de accesibilidad agregada esto es una
    aproximacion razonable; puede subestimar levemente el tiempo real en
    centros urbanos con calles de un solo sentido (ej. centro de Chiclayo).
  - La velocidad por tipo de via es un supuesto (tabla `VELOCIDADES_KMH`),
    no proviene de `maxspeed` real (ausente en la mayoria de vias peruanas
    en OSM). Se documenta y se puede ajustar en un solo lugar.
  - La red se extrae con un buffer alrededor de cada departamento (no se
    recorta exactamente en el limite politico), porque las rutas reales
    cruzan la frontera departamental con normalidad.
"""

from __future__ import annotations

import math
import os
import pickle
import time
from collections import Counter, defaultdict
from dataclasses import dataclass

import geopandas as gpd
import networkx as nx
import numpy as np
import osmium
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point

# ---------------------------------------------------------------------------
# Configuracion (ver config.md)
# ---------------------------------------------------------------------------

PERFILES = ("car", "foot", "bike")

# Tipos de via aceptados por perfil. Un tipo puede estar en mas de un perfil.
HIGHWAY_POR_PERFIL = {
    "car": {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "unclassified", "residential", "service", "track",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
        "tertiary_link", "living_street",
    },
    "foot": {
        "motorway", "trunk", "primary", "secondary", "tertiary",
        "unclassified", "residential", "service", "track",
        "motorway_link", "trunk_link", "primary_link", "secondary_link",
        "tertiary_link", "living_street",
        "footway", "path", "pedestrian", "steps", "bridleway",
    },
    "bike": {
        "trunk", "primary", "secondary", "tertiary", "unclassified",
        "residential", "service", "track", "living_street",
        "trunk_link", "primary_link", "secondary_link", "tertiary_link",
        "cycleway", "path",
    },
}
HIGHWAY_TODOS = set().union(*HIGHWAY_POR_PERFIL.values())

# Velocidad libre asumida (km/h) por tipo de via, usada para las 3 redes.
# El perfil car usa esta tabla; foot y bike usan una velocidad fija (mas abajo)
# salvo ajustes menores por tipo de superficie.
VELOCIDADES_CAR_KMH = {
    "motorway": 90, "motorway_link": 45,
    "trunk": 70, "trunk_link": 40,
    "primary": 55, "primary_link": 35,
    "secondary": 45, "secondary_link": 30,
    "tertiary": 35, "tertiary_link": 25,
    "unclassified": 30, "residential": 25, "living_street": 12,
    "service": 15, "track": 18,
}
VELOCIDAD_CAR_DEFAULT_KMH = 25

VELOCIDAD_FOOT_KMH = 4.5          # caminata llana estandar
VELOCIDAD_FOOT_TRACK_KMH = 3.5    # trocha / camino de tierra: mas lento
VELOCIDAD_BIKE_KMH = 14.0         # ciclismo urbano/rural promedio

BUFFER_DEG = 0.08  # ~8-9 km de margen alrededor de cada departamento

# Umbral de distancia de snap: si el nodo de red mas cercano esta a mas de
# esto, se considera que el punto NO logro engancharse a la red (fallo).
SNAP_FALLO_M = 5000

R_TIERRA_M = 6_371_000.0


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def log(msg: str, t0: float | None = None) -> None:
    ts = time.strftime("%H:%M:%S")
    extra = f" (+{time.time() - t0:.1f}s)" if t0 is not None else ""
    print(f"[{ts}] {msg}{extra}", flush=True)


def haversine_m(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(np.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2 * R_TIERRA_M * np.arcsin(np.sqrt(a))


def department_bbox(boundaries: gpd.GeoDataFrame, departamento: str, buffer_deg: float = BUFFER_DEG):
    sub = boundaries[boundaries["NOMBDEP"] == departamento]
    if sub.empty:
        raise ValueError(f"Departamento no encontrado en la capa de limites: {departamento}")
    minx, miny, maxx, maxy = sub.total_bounds
    return (minx - buffer_deg, miny - buffer_deg, maxx + buffer_deg, maxy + buffer_deg)


# ---------------------------------------------------------------------------
# 1. Extraccion cruda desde el .osm.pbf (una sola pasada para todos los
#    departamentos declarados -- leer el archivo completo es lo caro, no
#    filtrar por departamento).
# ---------------------------------------------------------------------------

class _ExtractorHandler(osmium.SimpleHandler):
    """Recolecta, por departamento, los nodos y tramos (edges) de las vias
    cuyo tag `highway` esta en HIGHWAY_TODOS y que tocan el bbox del depto."""

    def __init__(self, bboxes: dict[str, tuple]):
        super().__init__()
        self.bboxes = bboxes
        self.nodos = {dep: {} for dep in bboxes}       # dep -> {node_id: (lon,lat)}
        self.edges = {dep: [] for dep in bboxes}        # dep -> [(a,b,len_m,highway,oneway)]
        self.n_ways_totales = 0
        self.n_ways_relevantes = 0

    def way(self, w):
        self.n_ways_totales += 1
        hw = w.tags.get("highway")
        if hw is None or hw not in HIGHWAY_TODOS:
            return
        try:
            pts = [(n.ref, n.location.lon, n.location.lat) for n in w.nodes if n.location.valid()]
        except Exception:
            return
        if len(pts) < 2:
            return

        oneway = w.tags.get("oneway") in ("yes", "true", "1")

        for dep, (x0, y0, x1, y1) in self.bboxes.items():
            inside = any(x0 <= lo <= x1 and y0 <= la <= y1 for _, lo, la in pts)
            if not inside:
                continue
            self.n_ways_relevantes += 1
            nodos_dep = self.nodos[dep]
            for nid, lo, la in pts:
                if nid not in nodos_dep:
                    nodos_dep[nid] = (lo, la)
            for (a_id, a_lo, a_la), (b_id, b_lo, b_la) in zip(pts, pts[1:]):
                length_m = float(haversine_m(a_lo, a_la, b_lo, b_la))
                self.edges[dep].append((a_id, b_id, length_m, hw, oneway))


def extraer_redes_crudas(pbf_path: str, departamentos: dict[str, tuple], cache_dir: str) -> dict:
    """Extrae nodos+edges crudos de OSM para cada departamento (bbox ya
    calculado), en una unica pasada sobre el .pbf. Cachea el resultado por
    departamento -- una segunda corrida no vuelve a leer el .pbf."""
    os.makedirs(cache_dir, exist_ok=True)
    faltantes = {
        dep: bbox for dep, bbox in departamentos.items()
        if not os.path.exists(os.path.join(cache_dir, f"raw_{dep}.pkl"))
    }

    if faltantes:
        log(f"Extrayendo del .pbf (sin cache): {list(faltantes)} -- esto lee {os.path.basename(pbf_path)} completo")
        t0 = time.time()
        handler = _ExtractorHandler(faltantes)
        handler.apply_file(pbf_path, locations=True)
        log(f"  ways totales en el .pbf: {handler.n_ways_totales:,} | "
            f"ways relevantes (highway + bbox): {handler.n_ways_relevantes:,}", t0)
        for dep in faltantes:
            payload = {"nodos": handler.nodos[dep], "edges": handler.edges[dep]}
            with open(os.path.join(cache_dir, f"raw_{dep}.pkl"), "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            log(f"  {dep}: {len(payload['nodos']):,} nodos, {len(payload['edges']):,} tramos crudos -> cacheado")
    else:
        log("Extraccion cruda ya cacheada para todos los departamentos -- no se relee el .pbf")

    resultado = {}
    for dep in departamentos:
        with open(os.path.join(cache_dir, f"raw_{dep}.pkl"), "rb") as f:
            resultado[dep] = pickle.load(f)
    return resultado


# ---------------------------------------------------------------------------
# 2. Simplificacion: red cruda (un nodo por vertice de forma) -> grafo de
#    intersecciones (un nodo por interseccion/extremo real). Sin esto, los
#    grafos tienen millones de aristas y Dijkstra es impracticamente lento.
# ---------------------------------------------------------------------------

def _simplificar_a_intersecciones(nodos: dict, edges_tipo: list[tuple], perfil: str) -> tuple[dict, list]:
    """edges_tipo: lista de (a, b, length_m, highway). Devuelve
    (nodos_reales, edges_simplificados), donde cada edge simplificado es
    (a, b, length_total_m, time_total_min, highway_dominante).

    El tiempo de viaje se acumula segmento por segmento (cada uno con SU
    PROPIO tipo de via), no se recalcula al final desde la longitud total
    con un unico tipo de via -- una cadena colapsada casi nunca tiene un
    tramo crudo (a, b) directo que la represente entera, así que adivinar
    el tipo por el par de extremos de la cadena completa fallaria casi
    siempre y caeria al tipo por defecto. `highway_dominante` (el tipo del
    segmento mas largo de la cadena) queda solo como metadato informativo.
    """
    grado = Counter()
    for a, b, _l, _hw in edges_tipo:
        grado[a] += 1
        grado[b] += 1

    # Nodo "real" = interseccion (grado != 2) o extremo de una cadena.
    reales = {n for n, g in grado.items() if g != 2}

    # Adyacencia para caminar cadenas de nodos de paso (grado==2).
    adj = defaultdict(list)  # node -> [(vecino, length_m, highway, edge_idx)]
    for idx, (a, b, length_m, hw) in enumerate(edges_tipo):
        adj[a].append((b, length_m, hw, idx))
        adj[b].append((a, length_m, hw, idx))

    visitado = set()
    simplificados = []

    for inicio in reales:
        for vecino, length0, hw0, idx0 in adj[inicio]:
            clave = (idx0,)
            if clave in visitado:
                continue
            visitado.add(clave)
            total_len = length0
            total_time = _tiempo_min(length0, hw0, perfil)
            hw_dominante, len_dominante = hw0, length0
            prev, cur = inicio, vecino
            while cur not in reales:
                siguiente = None
                for v2, l2, hw2, idx2 in adj[cur]:
                    if v2 == prev:
                        continue
                    siguiente = (v2, l2, hw2, idx2)
                    break
                if siguiente is None:
                    break  # cadena rota (no deberia pasar en datos limpios)
                v2, l2, hw2, idx2 = siguiente
                visitado.add((idx2,))
                total_len += l2
                total_time += _tiempo_min(l2, hw2, perfil)
                if l2 > len_dominante:
                    hw_dominante, len_dominante = hw2, l2
                prev, cur = cur, v2
            if cur in nodos and inicio in nodos:
                simplificados.append((inicio, cur, total_len, total_time, hw_dominante))

    nodos_reales = {n: nodos[n] for n in reales if n in nodos}
    return nodos_reales, simplificados


def construir_grafo(raw: dict, perfil: str) -> nx.Graph:
    """Construye el grafo NetworkX (no dirigido) para un perfil a partir de
    la extraccion cruda de un departamento."""
    nodos = raw["nodos"]
    tipos_ok = HIGHWAY_POR_PERFIL[perfil]
    edges_tipo = [(a, b, l, hw) for (a, b, l, hw, _oneway) in raw["edges"] if hw in tipos_ok]

    nodos_reales, simplificados = _simplificar_a_intersecciones(nodos, edges_tipo, perfil)

    g = nx.Graph()
    for nid, (lon, lat) in nodos_reales.items():
        g.add_node(nid, x=lon, y=lat)

    for a, b, length_m, tiempo_min, hw in simplificados:
        if a == b or length_m <= 0:
            continue
        if g.has_edge(a, b) and g[a][b]["length_m"] <= length_m:
            continue
        g.add_edge(a, b, length_m=length_m, travel_time_min=tiempo_min, highway=hw)

    return g


def _tiempo_min(length_m: float, highway: str, perfil: str) -> float:
    km = length_m / 1000.0
    if perfil == "car":
        v = VELOCIDADES_CAR_KMH.get(highway, VELOCIDAD_CAR_DEFAULT_KMH)
    elif perfil == "foot":
        v = VELOCIDAD_FOOT_TRACK_KMH if highway == "track" else VELOCIDAD_FOOT_KMH
    else:  # bike
        v = VELOCIDAD_BIKE_KMH
    return (km / v) * 60.0


# ---------------------------------------------------------------------------
# 3. Snapping de puntos a la red
# ---------------------------------------------------------------------------

@dataclass
class ResultadoSnap:
    node_id: object
    dist_m: float
    ok: bool


def snap_puntos(lons: np.ndarray, lats: np.ndarray, g: nx.Graph) -> list[ResultadoSnap]:
    if g.number_of_nodes() == 0:
        return [ResultadoSnap(None, np.inf, False) for _ in lons]

    ids = list(g.nodes)
    xs = np.array([g.nodes[n]["x"] for n in ids])
    ys = np.array([g.nodes[n]["y"] for n in ids])
    # Aproximacion plana local para el KD-tree (suficiente para nearest-node
    # a escala departamental); la distancia real se recalcula con haversine.
    tree = cKDTree(np.column_stack([xs, ys]))
    _, idx = tree.query(np.column_stack([lons, lats]), k=1)

    resultados = []
    for i, node_idx in enumerate(idx):
        nid = ids[node_idx]
        d = haversine_m(lons[i], lats[i], xs[node_idx], ys[node_idx])
        resultados.append(ResultadoSnap(nid, float(d), d <= SNAP_FALLO_M))
    return resultados


# ---------------------------------------------------------------------------
# 4. Matrices de tiempo/distancia -- Dijkstra desde cada FACILIDAD (pocas),
#    no desde cada punto de demanda (muchos). Es matematicamente equivalente
#    para un grafo no dirigido (que es lo que construimos) y ~100x mas barato
#    cuando #facilidades << #puntos_de_demanda.
# ---------------------------------------------------------------------------

def matriz_desde_facilidades(g: nx.Graph, nodos_facilidad: list, weight: str = "travel_time_min") -> dict:
    """Devuelve {facilidad_node_id: {nodo: costo}} usando Dijkstra por facilidad."""
    salida = {}
    for nid in nodos_facilidad:
        if nid is None or nid not in g:
            salida[nid] = {}
            continue
        salida[nid] = nx.single_source_dijkstra_path_length(g, nid, weight=weight)
    return salida


def construir_matriz_completa(
    demanda_ids, demanda_snap: list[ResultadoSnap],
    facilidad_ids, facilidad_snap: list[ResultadoSnap],
    g: nx.Graph,
) -> pd.DataFrame:
    """Matriz origen x facilidad (formato largo) en tiempo (min) y distancia (m)."""
    nodos_fac = [s.node_id for s in facilidad_snap]
    tiempos = matriz_desde_facilidades(g, nodos_fac, weight="travel_time_min")
    distancias = matriz_desde_facilidades(g, nodos_fac, weight="length_m")

    filas = []
    for d_id, d_snap in zip(demanda_ids, demanda_snap):
        for f_id, f_snap in zip(facilidad_ids, facilidad_snap):
            if not d_snap.ok or not f_snap.ok:
                filas.append((d_id, f_id, np.nan, np.nan, False, "SIN_SNAP"))
                continue
            t = tiempos.get(f_snap.node_id, {}).get(d_snap.node_id, np.nan)
            dist = distancias.get(f_snap.node_id, {}).get(d_snap.node_id, np.nan)
            if pd.isna(t):
                filas.append((d_id, f_id, np.nan, np.nan, False, "NO_ROUTEABLE"))
            else:
                filas.append((d_id, f_id, t, dist, True, "ROUTED"))

    return pd.DataFrame(filas, columns=[
        "demand_id", "facility_id", "time_min", "distance_m", "routed_ok", "estado",
    ])


def nearest_optimo(
    g: nx.Graph,
    origen_ids, origen_snap: list[ResultadoSnap],
    destino_ids, destino_snap: list[ResultadoSnap],
    weight: str = "travel_time_min",
) -> dict:
    """Calcula, para cada origen, el destino mas cercano segun `weight`.

    Corre Dijkstra desde el lado con MENOS puntos (origen o destino) -- el
    costo de una corrida de Dijkstra depende del tamano del grafo, no de
    cuantos puntos se consultan despues, asi que conviene sembrar desde el
    conjunto mas chico. Devuelve {origen_id: (destino_id, costo) | None}.
    """
    origenes_ok = [(oid, s.node_id) for oid, s in zip(origen_ids, origen_snap) if s.ok]
    destinos_ok = [(did, s.node_id) for did, s in zip(destino_ids, destino_snap) if s.ok]
    if not origenes_ok or not destinos_ok:
        return {oid: None for oid in origen_ids}

    resultado = {oid: None for oid in origen_ids}

    if len(origenes_ok) <= len(destinos_ok):
        for oid, onode in origenes_ok:
            if onode not in g:
                continue
            dist = nx.single_source_dijkstra_path_length(g, onode, weight=weight)
            mejor = None
            for did, dnode in destinos_ok:
                c = dist.get(dnode)
                if c is not None and (mejor is None or c < mejor[1]):
                    mejor = (did, c)
            resultado[oid] = mejor
    else:
        por_destino = {}
        for did, dnode in destinos_ok:
            if dnode not in g:
                continue
            por_destino[did] = nx.single_source_dijkstra_path_length(g, dnode, weight=weight)
        for oid, onode in origenes_ok:
            mejor = None
            for did, tabla in por_destino.items():
                c = tabla.get(onode)
                if c is not None and (mejor is None or c < mejor[1]):
                    mejor = (did, c)
            resultado[oid] = mejor

    return resultado


def nearest_from_matrix(matriz_larga: pd.DataFrame) -> pd.DataFrame:
    validas = matriz_larga[matriz_larga["routed_ok"]]
    if validas.empty:
        return matriz_larga.iloc[0:0][["demand_id", "facility_id", "time_min", "distance_m"]]
    idx = validas.groupby("demand_id")["time_min"].idxmin()
    return validas.loc[idx, ["demand_id", "facility_id", "time_min", "distance_m"]].reset_index(drop=True)
