# Golden Hour — Acceso vial a salud resolutiva (Perú)

Proyecto integrador: cuánto tarda, por vía terrestre, la población de
Lambayeque (costa), Junín (sierra) y Loreto (selva) en llegar a un
establecimiento de salud con capacidad resolutiva (categoría II-1 o
superior), y dónde están las peores brechas.

Todos los parámetros del análisis (departamentos, categorías, umbrales,
rutas, motor de ruteo) están declarados en [`config.md`](config.md) — para
correr el pipeline sobre otros departamentos, se edita ese archivo, no el
código.

## Estructura

```
config.md                  parámetros del proyecto
requirements.txt
src/
  routing.py                Fase 2 — extracción OSM, grafo, snapping, matrices
  metrics.py                Fase 3 — métricas de acceso (funciones puras)
  export.py                 Fase 5 — figuras (PDF) y tablas (LaTeX/booktabs) para el reporte
data/
  RENIPRESS_*.csv            Fase 1 — oferta (RENIPRESS/SUSALUD)
  CP_MED/                    Fase 1 — demanda (SIGMED/MINEDU, centros poblados)
  peru-*.osm.pbf              red vial (Geofabrik)
  CodigoV2.ipynb              Fase 1 — adquisición y validación
  Fase2_Routing.ipynb         Fase 2 — routing (orquesta src/routing.py)
  Fase3_Metricas.ipynb        Fase 3 — métricas (orquesta src/metrics.py)
  raw/                        boundaries, población INEI, extracción OSM cacheada
  processed/                  GeoParquet: oferta, demanda, matrices, muestras
  outputs/                    CSV: reporte de calidad, métricas, tablas del reporte
app.py                       Fase 4 — dashboard Streamlit
report/
  main.tex, figures/          Fase 5 — reporte LaTeX
logs/                        logs de ejecución (calidad de datos, routing)
```

## Instalación

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Datos

RENIPRESS y SIGMED (`data/CP_MED/`) ya están en el repo. El extracto OSM de
Perú **no** está commiteado (244 MB, excede el límite de 100 MB de
GitHub) -- descárgalo una vez:

```bash
curl -o data/peru-260905.osm.pbf https://download.geofabrik.de/south-america/peru-latest.osm.pbf
```

Fuentes adicionales se descargan automáticamente la primera vez que corre
el pipeline y quedan cacheadas en `data/raw/` (no versionadas, salvo la
población distrital que sí se commitea vía `data/outputs/`):
- Límites distritales (INEI/IGN, vía `juaneladio/peru-geojson`).
- Población distrital 2017 (INEI, vía `geodir/ubigeo-peru`).
- `data/raw/osm_extract/*.pkl`: cache de la red vial cruda, se regenera
  leyendo el `.pbf` una sola vez (~2.5 min) la primera vez que corres
  `data/Fase2_Routing.ipynb`.

## Cómo correr el pipeline completo

En orden (cada notebook es re-ejecutable: si el archivo de salida ya existe,
no recalcula):

1. `data/CodigoV2.ipynb` — Fase 1: limpia RENIPRESS y SIGMED, valida
   coordenadas/categorías/duplicados/encoding/polígono distrital, exporta
   `data/processed/establecimientos_salud.parquet` y
   `centros_poblados_demanda.parquet`, y el reporte de calidad en
   `data/outputs/`.
2. `data/Fase2_Routing.ipynb` — Fase 2: construye la red vial (pyosmium +
   NetworkX) por departamento y perfil (auto/bici/a pie), snapea los puntos,
   calcula la matriz completa demanda×resolutivo en auto y las comparaciones
   entre modos. Motor y parámetros documentados en `config.md`.
3. `data/Fase3_Metricas.ipynb` — Fase 3: cobertura por bandas, acceso
   ponderado por población (distrito/provincia/departamento), brechas
   críticas, Gini/Lorenz, contraste urbano/rural, cruce con densidad
   poblacional.

## Dashboard

```bash
streamlit run app.py
```

El dashboard **solo lee** los archivos precomputados de `data/processed/` y
`data/outputs/` — no vuelve a rutear ni reconstruye grafos al cargar.

## Motor de ruteo (por qué no OSRM/pyrosm)

Docker no está disponible en el entorno de desarrollo, y `pyrosm` (la forma
más directa de alimentar OSMnx desde un `.pbf` local) requiere un compilador
de C++ que tampoco está instalado. La alternativa sin dependencias nativas
pesadas es `pyosmium` (bindings de libosmium con wheels precompiladas) para
leer el `.osm.pbf`, combinado con un grafo propio en `networkx` — la opción
"OSMnx + NetworkX" que el enunciado ofrece como alternativa a OSRM. Detalles
y simplificaciones declaradas en el docstring de [`src/routing.py`](src/routing.py).

## Reporte LaTeX

`report/main.tex` está completo (con las cifras reales de la corrida
actual) y ya está compilado en `report/main.pdf` (MiKTeX). Para
recompilarlo tras un cambio:

```bash
# Opción rápida: subir report/ a Overleaf y compilar ahí.
# Opción local (requiere una distribución LaTeX -- MiKTeX o TeX Live):
cd report
pdflatex -interaction=nonstopmode main.tex
pdflatex -interaction=nonstopmode main.tex   # dos pasadas, por las referencias cruzadas
```

Antes de compilar, corre `python -m src.export` (raíz del repo) para
regenerar las figuras (`report/figures/*.pdf`) y tablas
(`report/tables/*.tex`) desde los datos más recientes de
`data/outputs/`.

## Limitaciones (resumen — ver Fase 5 para el detalle)

- Red vial no dirigida (se ignoran restricciones de sentido único).
- Velocidades por tipo de vía son un supuesto, no vienen de `maxspeed` real.
- Sin población a nivel de centro poblado: se reparte la población
  distrital (INEI) en partes iguales entre los centros poblados del mismo
  distrito.
- Límites distritales de una fuente comunitaria (no el shapefile oficial de
  INEI/IDEP), por no estar disponible en el entorno.
