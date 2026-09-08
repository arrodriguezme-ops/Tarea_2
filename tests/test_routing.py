"""
Tests unitarios de src/routing.py -- corren en segundos, sin depender del
.osm.pbf (244 MB) ni de ningun archivo externo. Verifican cada pieza del
modulo de forma aislada, tal como pide la Fase 2 ("the routing module must
be importable and testable independently of the pipeline").

Correr: `pytest tests/ -v` desde la raiz del repo.
"""

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from src import routing as R


# ---------------------------------------------------------------------------
# haversine_m
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_mismo_punto_distancia_cero(self):
        assert R.haversine_m(-77.0, -12.0, -77.0, -12.0) == pytest.approx(0.0, abs=1e-6)

    def test_un_grado_de_latitud_en_el_ecuador(self):
        # 1 grado de latitud son ~111.19 km en cualquier parte del globo
        d = R.haversine_m(0.0, 0.0, 0.0, 1.0)
        assert d == pytest.approx(111_195, rel=0.01)

    def test_distancia_conocida_lima_arequipa(self):
        # Lima (-77.0428,-12.0464) -> Arequipa (-71.5375,-16.4090): ~800 km reales
        d_km = R.haversine_m(-77.0428, -12.0464, -71.5375, -16.4090) / 1000
        assert 700 < d_km < 900

    def test_es_simetrica(self):
        a = R.haversine_m(-80.0, -5.0, -75.0, -10.0)
        b = R.haversine_m(-75.0, -10.0, -80.0, -5.0)
        assert a == pytest.approx(b)

    def test_acepta_arrays_numpy(self):
        lons1 = np.array([-77.0, -71.5])
        lats1 = np.array([-12.0, -16.4])
        lons2 = np.array([-77.0, -71.5])
        lats2 = np.array([-12.1, -16.5])
        d = R.haversine_m(lons1, lats1, lons2, lats2)
        assert isinstance(d, np.ndarray)
        assert (d > 0).all()


# ---------------------------------------------------------------------------
# department_bbox
# ---------------------------------------------------------------------------

class TestDepartmentBbox:
    @pytest.fixture
    def boundaries(self):
        # Un "departamento" cuadrado de 1x1 grado, centrado en (-77, -12).
        cuadrado = Polygon([(-77.5, -12.5), (-76.5, -12.5), (-76.5, -11.5), (-77.5, -11.5)])
        return gpd.GeoDataFrame({"NOMBDEP": ["TESTDEP"]}, geometry=[cuadrado], crs="EPSG:4326")

    def test_bbox_incluye_el_buffer(self, boundaries):
        bbox = R.department_bbox(boundaries, "TESTDEP", buffer_deg=0.1)
        minx, miny, maxx, maxy = bbox
        assert minx == pytest.approx(-77.6)
        assert maxx == pytest.approx(-76.4)
        assert miny == pytest.approx(-12.6)
        assert maxy == pytest.approx(-11.4)

    def test_departamento_inexistente_lanza_error(self, boundaries):
        with pytest.raises(ValueError):
            R.department_bbox(boundaries, "NO_EXISTE")


# ---------------------------------------------------------------------------
# _tiempo_min (velocidades asumidas por perfil / tipo de via)
# ---------------------------------------------------------------------------

class TestTiempoMin:
    def test_car_usa_velocidad_de_la_tabla(self):
        # 90 km/h en motorway: 90 km -> 60 min
        t = R._tiempo_min(90_000, "motorway", "car")
        assert t == pytest.approx(60.0)

    def test_car_categoria_desconocida_usa_default(self):
        t_default = R._tiempo_min(25_000, "highway_type_inexistente", "car")
        t_esperado = 25 / R.VELOCIDAD_CAR_DEFAULT_KMH * 60
        assert t_default == pytest.approx(t_esperado)

    def test_foot_es_mas_lento_que_car_en_la_misma_via(self):
        t_car = R._tiempo_min(10_000, "residential", "car")
        t_foot = R._tiempo_min(10_000, "residential", "foot")
        assert t_foot > t_car

    def test_foot_en_trocha_es_mas_lento_que_foot_normal(self):
        t_track = R._tiempo_min(5_000, "track", "foot")
        t_normal = R._tiempo_min(5_000, "residential", "foot")
        assert t_track > t_normal

    def test_bike_entre_car_y_foot(self):
        t_car = R._tiempo_min(10_000, "residential", "car")
        t_bike = R._tiempo_min(10_000, "residential", "bike")
        t_foot = R._tiempo_min(10_000, "residential", "foot")
        assert t_car < t_bike < t_foot

    def test_distancia_cero_toma_cero_minutos(self):
        assert R._tiempo_min(0, "residential", "car") == 0.0


# ---------------------------------------------------------------------------
# _simplificar_a_intersecciones / construir_grafo
# ---------------------------------------------------------------------------

def _raw_sintetico():
    """Red sintetica: una cadena 1-2-3 (2 es un nodo de paso, grado 2) y dos
    ramales desde la interseccion 3 hacia 4 y hacia 5. Coordenadas en grados,
    longitudes de tramo asignadas a mano (no derivan de las coordenadas)."""
    nodos = {
        1: (-77.000, -12.000),
        2: (-77.000, -12.001),
        3: (-77.000, -12.002),
        4: (-76.999, -12.002),
        5: (-77.000, -12.003),
    }
    edges = [
        (1, 2, 100.0, "residential", False),
        (2, 3, 150.0, "residential", False),
        (3, 4, 200.0, "residential", False),
        (3, 5, 300.0, "tertiary", False),
    ]
    return {"nodos": nodos, "edges": edges}


class TestSimplificacion:
    def test_colapsa_el_nodo_de_paso(self):
        raw = _raw_sintetico()
        edges_tipo = [(a, b, l, hw) for a, b, l, hw, o in raw["edges"]]
        nodos_reales, simplificados = R._simplificar_a_intersecciones(raw["nodos"], edges_tipo, "car")

        # El nodo 2 (grado 2, de paso) no debe sobrevivir como nodo real.
        assert 2 not in nodos_reales
        assert {1, 3, 4, 5} <= set(nodos_reales)

        # La cadena 1-2-3 se colapsa en un solo tramo 1-3 de 250m (100+150).
        longitudes = {frozenset((a, b)): total_len for a, b, total_len, _t, _hw in simplificados}
        assert longitudes[frozenset((1, 3))] == pytest.approx(250.0)
        assert longitudes[frozenset((3, 4))] == pytest.approx(200.0)
        assert longitudes[frozenset((3, 5))] == pytest.approx(300.0)

    def test_tiempo_se_acumula_por_segmento_no_por_tipo_del_extremo(self):
        # Cadena 1-2-3 con 2 tramos "residential": el tiempo debe ser la
        # SUMA de ambos tramos calculados con su propio tipo, no el tiempo
        # de 250m completos adivinando un tipo -- este es el bug que se
        # corrigio (antes caia al tipo por defecto "unclassified").
        raw = _raw_sintetico()
        edges_tipo = [(a, b, l, hw) for a, b, l, hw, o in raw["edges"]]
        _, simplificados = R._simplificar_a_intersecciones(raw["nodos"], edges_tipo, "car")
        tiempos = {frozenset((a, b)): t for a, b, _l, t, _hw in simplificados}

        esperado = R._tiempo_min(100.0, "residential", "car") + R._tiempo_min(150.0, "residential", "car")
        assert tiempos[frozenset((1, 3))] == pytest.approx(esperado)

    def test_construir_grafo_conserva_longitud_total_de_la_cadena(self):
        raw = _raw_sintetico()
        g = R.construir_grafo(raw, "car")

        assert set(g.nodes) == {1, 3, 4, 5}
        assert g.has_edge(1, 3)
        assert g[1][3]["length_m"] == pytest.approx(250.0)

    def test_construir_grafo_asigna_tiempo_segun_tipo_de_via(self):
        raw = _raw_sintetico()
        g = R.construir_grafo(raw, "car")
        # El tramo 1-3 (cadena de 2 segmentos "residential") y el tramo 3-5
        # ("tertiary", un solo segmento) deben usar cada uno su propia
        # velocidad -- no la del tipo por defecto.
        t_residencial = g[1][3]["travel_time_min"]
        t_terciaria = g[3][5]["travel_time_min"]
        esperado_residencial = R._tiempo_min(100.0, "residential", "car") + R._tiempo_min(150.0, "residential", "car")
        esperado_terciaria = R._tiempo_min(300.0, "tertiary", "car")
        assert t_residencial == pytest.approx(esperado_residencial)
        assert t_terciaria == pytest.approx(esperado_terciaria)

    def test_perfil_foot_incluye_mas_tipos_de_via_que_bike(self):
        # "footway" esta en el whitelist de foot pero no en el de bike/car
        assert "footway" in R.HIGHWAY_POR_PERFIL["foot"]
        assert "footway" not in R.HIGHWAY_POR_PERFIL["bike"]
        assert "footway" not in R.HIGHWAY_POR_PERFIL["car"]


# ---------------------------------------------------------------------------
# snap_puntos
# ---------------------------------------------------------------------------

class TestSnapPuntos:
    @pytest.fixture
    def grafo_simple(self):
        g = nx.Graph()
        g.add_node("A", x=-77.000, y=-12.000)
        g.add_node("B", x=-77.010, y=-12.010)
        g.add_edge("A", "B", length_m=1000, travel_time_min=2.0)
        return g

    def test_punto_exacto_sobre_un_nodo_engancha_con_distancia_casi_cero(self, grafo_simple):
        resultados = R.snap_puntos(np.array([-77.000]), np.array([-12.000]), grafo_simple)
        assert len(resultados) == 1
        assert resultados[0].node_id == "A"
        assert resultados[0].ok
        assert resultados[0].dist_m < 1.0

    def test_punto_lejano_falla_el_snap(self, grafo_simple):
        # ~1 grado de distancia (~111 km) >> el umbral de 5000 m
        resultados = R.snap_puntos(np.array([-78.0]), np.array([-13.0]), grafo_simple)
        assert not resultados[0].ok
        assert resultados[0].dist_m > R.SNAP_FALLO_M

    def test_grafo_vacio_falla_todo_el_snap(self):
        g_vacio = nx.Graph()
        resultados = R.snap_puntos(np.array([-77.0, -76.0]), np.array([-12.0, -11.0]), g_vacio)
        assert len(resultados) == 2
        assert all(not r.ok for r in resultados)
        assert all(r.node_id is None for r in resultados)


# ---------------------------------------------------------------------------
# matriz_desde_facilidades / construir_matriz_completa
# ---------------------------------------------------------------------------

class TestMatrices:
    @pytest.fixture
    def grafo_lineal(self):
        # A --10min-- B --5min-- C
        g = nx.Graph()
        g.add_edge("A", "B", travel_time_min=10.0, length_m=1000.0)
        g.add_edge("B", "C", travel_time_min=5.0, length_m=500.0)
        return g

    def test_matriz_desde_facilidades_da_distancias_correctas(self, grafo_lineal):
        salida = R.matriz_desde_facilidades(grafo_lineal, ["B"], weight="travel_time_min")
        assert salida["B"]["A"] == pytest.approx(10.0)
        assert salida["B"]["C"] == pytest.approx(5.0)
        assert salida["B"]["B"] == pytest.approx(0.0)

    def test_matriz_desde_facilidades_nodo_ausente_da_diccionario_vacio(self, grafo_lineal):
        salida = R.matriz_desde_facilidades(grafo_lineal, ["ZZZ"], weight="travel_time_min")
        assert salida["ZZZ"] == {}

    def test_construir_matriz_completa_marca_rutas_validas(self, grafo_lineal):
        demanda_ids = ["d1"]
        demanda_snap = [R.ResultadoSnap(node_id="A", dist_m=0.0, ok=True)]
        facilidad_ids = ["f1"]
        facilidad_snap = [R.ResultadoSnap(node_id="C", dist_m=0.0, ok=True)]

        matriz = R.construir_matriz_completa(demanda_ids, demanda_snap, facilidad_ids, facilidad_snap, grafo_lineal)

        assert len(matriz) == 1
        fila = matriz.iloc[0]
        assert fila["estado"] == "ROUTED"
        assert fila["routed_ok"]
        assert fila["time_min"] == pytest.approx(15.0)  # A->B->C = 10+5
        assert fila["distance_m"] == pytest.approx(1500.0)

    def test_construir_matriz_completa_marca_sin_snap(self, grafo_lineal):
        demanda_ids = ["d1"]
        demanda_snap = [R.ResultadoSnap(node_id=None, dist_m=np.inf, ok=False)]
        facilidad_ids = ["f1"]
        facilidad_snap = [R.ResultadoSnap(node_id="C", dist_m=0.0, ok=True)]

        matriz = R.construir_matriz_completa(demanda_ids, demanda_snap, facilidad_ids, facilidad_snap, grafo_lineal)
        fila = matriz.iloc[0]
        assert fila["estado"] == "SIN_SNAP"
        assert not fila["routed_ok"]
        assert pd.isna(fila["time_min"])

    def test_construir_matriz_completa_marca_no_ruteable(self):
        # Grafo con dos componentes desconectadas: A-B y C (aislado)
        g = nx.Graph()
        g.add_edge("A", "B", travel_time_min=1.0, length_m=100.0)
        g.add_node("C", x=0, y=0)

        demanda_ids = ["d1"]
        demanda_snap = [R.ResultadoSnap(node_id="A", dist_m=0.0, ok=True)]
        facilidad_ids = ["f1"]
        facilidad_snap = [R.ResultadoSnap(node_id="C", dist_m=0.0, ok=True)]

        matriz = R.construir_matriz_completa(demanda_ids, demanda_snap, facilidad_ids, facilidad_snap, g)
        fila = matriz.iloc[0]
        assert fila["estado"] == "NO_ROUTEABLE"
        assert not fila["routed_ok"]


# ---------------------------------------------------------------------------
# nearest_optimo -- debe dar el mismo resultado sin importar de que lado
# (origen o destino) siembra Dijkstra, que es la optimizacion central del
# modulo (ver docstring de la funcion).
# ---------------------------------------------------------------------------

class TestNearestOptimo:
    @pytest.fixture
    def grafo_estrella(self):
        # Centro "O", con 3 puntas a distancias distintas.
        g = nx.Graph()
        g.add_edge("O", "cerca", travel_time_min=5.0)
        g.add_edge("O", "medio", travel_time_min=15.0)
        g.add_edge("O", "lejos", travel_time_min=30.0)
        return g

    def test_pocos_origenes_muchos_destinos(self, grafo_estrella):
        # 1 origen, 3 destinos -> debe sembrar Dijkstra desde el origen
        origen_ids = ["o1"]
        origen_snap = [R.ResultadoSnap("O", 0.0, True)]
        destino_ids = ["cerca", "medio", "lejos"]
        destino_snap = [
            R.ResultadoSnap("cerca", 0.0, True),
            R.ResultadoSnap("medio", 0.0, True),
            R.ResultadoSnap("lejos", 0.0, True),
        ]
        resultado = R.nearest_optimo(grafo_estrella, origen_ids, origen_snap, destino_ids, destino_snap)
        assert resultado["o1"] == ("cerca", pytest.approx(5.0))

    def test_muchos_origenes_pocos_destinos(self, grafo_estrella):
        # 3 origenes, 1 destino -> debe sembrar Dijkstra desde el destino
        origen_ids = ["cerca", "medio", "lejos"]
        origen_snap = [
            R.ResultadoSnap("cerca", 0.0, True),
            R.ResultadoSnap("medio", 0.0, True),
            R.ResultadoSnap("lejos", 0.0, True),
        ]
        destino_ids = ["o1"]
        destino_snap = [R.ResultadoSnap("O", 0.0, True)]

        resultado = R.nearest_optimo(grafo_estrella, origen_ids, origen_snap, destino_ids, destino_snap)
        assert resultado["cerca"] == ("o1", pytest.approx(5.0))
        assert resultado["medio"] == ("o1", pytest.approx(15.0))
        assert resultado["lejos"] == ("o1", pytest.approx(30.0))

    def test_sin_destinos_validos_devuelve_none(self, grafo_estrella):
        origen_ids = ["o1"]
        origen_snap = [R.ResultadoSnap("O", 0.0, True)]
        destino_ids = ["x"]
        destino_snap = [R.ResultadoSnap(None, np.inf, False)]  # fallo de snap

        resultado = R.nearest_optimo(grafo_estrella, origen_ids, origen_snap, destino_ids, destino_snap)
        assert resultado == {"o1": None}

    def test_nodo_inalcanzable_no_se_elige(self, grafo_estrella):
        grafo_estrella.add_node("isla")  # componente desconectada
        origen_ids = ["o1"]
        origen_snap = [R.ResultadoSnap("O", 0.0, True)]
        destino_ids = ["cerca", "isla"]
        destino_snap = [R.ResultadoSnap("cerca", 0.0, True), R.ResultadoSnap("isla", 0.0, True)]

        resultado = R.nearest_optimo(grafo_estrella, origen_ids, origen_snap, destino_ids, destino_snap)
        assert resultado["o1"][0] == "cerca"


# ---------------------------------------------------------------------------
# nearest_from_matrix
# ---------------------------------------------------------------------------

class TestNearestFromMatrix:
    def test_elige_el_minimo_por_punto_de_demanda(self):
        matriz = pd.DataFrame([
            {"demand_id": "d1", "facility_id": "f1", "time_min": 20.0, "distance_m": 2000, "routed_ok": True},
            {"demand_id": "d1", "facility_id": "f2", "time_min": 10.0, "distance_m": 1000, "routed_ok": True},
            {"demand_id": "d2", "facility_id": "f1", "time_min": 5.0, "distance_m": 500, "routed_ok": True},
        ])
        resultado = R.nearest_from_matrix(matriz)
        d1 = resultado[resultado["demand_id"] == "d1"].iloc[0]
        assert d1["facility_id"] == "f2"
        assert d1["time_min"] == pytest.approx(10.0)

    def test_ignora_filas_no_ruteadas(self):
        matriz = pd.DataFrame([
            {"demand_id": "d1", "facility_id": "f1", "time_min": np.nan, "distance_m": np.nan, "routed_ok": False},
            {"demand_id": "d1", "facility_id": "f2", "time_min": 30.0, "distance_m": 3000, "routed_ok": True},
        ])
        resultado = R.nearest_from_matrix(matriz)
        assert len(resultado) == 1
        assert resultado.iloc[0]["facility_id"] == "f2"

    def test_matriz_vacia_devuelve_dataframe_vacio(self):
        matriz = pd.DataFrame([
            {"demand_id": "d1", "facility_id": "f1", "time_min": np.nan, "distance_m": np.nan, "routed_ok": False},
        ])
        resultado = R.nearest_from_matrix(matriz)
        assert len(resultado) == 0
