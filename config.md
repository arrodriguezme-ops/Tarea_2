# Configuración del proyecto — Golden Hour

Todos los parámetros del pipeline viven aquí. El código (`src/`, notebooks)
lee estos valores; **no se deben hardcodear** en las celdas.

## Alcance geográfico (obligatorio: 1 costa + 1 sierra + 1 selva)

| Departamento | Región geográfica |
|---|---|
| LAMBAYEQUE | Costa |
| JUNIN | Sierra (andino) |
| LORETO | Selva (amazónico) |

> Cambiar el análisis de departamento: edita esta tabla únicamente.
> El código lee `DEPARTAMENTOS = {"LAMBAYEQUE", "JUNIN", "LORETO"}`.

## Definición de capacidad resolutiva

Un establecimiento es **resolutivo** si y solo si:
- `ESTADO` normalizado ∈ `{ACTIVO}`, **y**
- `CATEGORIA` normalizada ∈ `{II-1, II-2, II-E, III-1, III-2, III-E}`

Categorías no resolutivas (se mantienen en el dataset, se excluyen del cálculo
de ruteo): `I-1, I-2, I-3, I-4`.

Estados no activos (se mantienen, se excluyen del cálculo):
`BAJA DEFINITIVA`, `BAJA DEFINITIVA DE OFICIO`, `BAJA PROVISIONAL`,
`BAJA PROVISIONAL DE OFICIO`, `CIERRE TEMPORAL DE OFICIO`,
`CIERRE TEMPORAL DE PARTE`, `SIN ESTADO`.

## Umbrales de validación de coordenadas

| Parámetro | Valor |
|---|---|
| `LAT_MIN` | -18.4 |
| `LAT_MAX` | -0.04 |
| `LON_MIN` | -81.4 |
| `LON_MAX` | -68.6 |
| `EPS_CERO` (tolerancia para considerar una coordenada "cero") | 1e-3 |

## Rutas de datos

| Variable | Ruta |
|---|---|
| `RENIPRESS_PATH` | `data/RENIPRESS_30-04-2026.csv` (fecha de descarga: 2026-04-30) |
| `CP_MED_PATH` | `data/CP_MED/CP_P.shp` (SIGMED, centros poblados) |
| `BOUNDARIES_URL` | `https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_distrital_simple.geojson` |
| `BOUNDARIES_PATH` | `data/raw/boundaries/peru_distrital_simple.geojson` (cacheado, no se re-descarga si ya existe) |
| `PROCESSED_DIR` | `data/processed/` |
| `OUTPUTS_DIR` | `data/outputs/` |
| `LOGS_DIR` | `logs/` |

> **Nota sobre límites administrativos:** el enunciado exige límites
> distrital/provincial/departamental de una fuente oficial. Se usó un extracto
> público derivado de INEI/IGN (`juaneladio/peru-geojson`) como sustituto
> reproducible mientras no se dispone de la capa oficial de INEI/IDEP. Esto se
> declara como limitación en el reporte (Fase 5).

## Routing (Fase 2)

| Parámetro | Valor |
|---|---|
| Motor usado | `pyosmium` + `NetworkX` (ver `src/routing.py`) — Docker no disponible en el entorno de desarrollo, y `pyrosm` requiere compilador C++ no instalado |
| Perfiles | car, foot, bike |
| Grafo | no dirigido (se ignora `oneway`); simplificado a intersecciones reales antes de rutear |
| Velocidades por tipo de vía | supuesto documentado en `src/routing.VELOCIDADES_CAR_KMH` / `VELOCIDAD_FOOT_KMH` / `VELOCIDAD_BIKE_KMH` — no viene de `maxspeed` real |
| Buffer alrededor de cada departamento | 0.08° (~8-9 km), para no cortar rutas que cruzan el límite político |
| Umbral de fallo de snap | 5000 m |
| Máximo de puntos de demanda | 5000 (de 13,358) — muestreo estratificado por distrito, con corrección de peso muestral (ver `data/Fase2_Routing.ipynb`, sección 2) para que los totales de población sigan siendo correctos |
| Semilla de muestreo | 42 |
| Población distrital | INEI censo 2017, vía `geodir/ubigeo-peru` (repartida en partes iguales entre los centros poblados de cada distrito — SIGMED no trae población por centro poblado) |
| Regla de "urbano" (Fase 2/3) | centro poblado es capital de distrito, provincia o departamento (`CAPITAL != 0` en SIGMED) |

## Categorías / whitelist (referencia rápida para el código)

```text
CATEGORIAS_RESOLUTIVAS     = {"II-1","II-2","II-E","III-1","III-2","III-E"}
CATEGORIAS_NO_RESOLUTIVAS  = {"I-1","I-2","I-3","I-4"}
SIN_CATEGORIA               = {"0","SIN CATEGORIA"}
ESTADOS_ACTIVOS              = {"ACTIVO"}
ESTADOS_NO_ACTIVOS = {
    "BAJA DEFINITIVA", "BAJA DEFINITIVA DE OFICIO", "BAJA PROVISIONAL",
    "BAJA PROVISIONAL DE OFICIO", "CIERRE TEMPORAL DE OFICIO",
    "CIERRE TEMPORAL DE PARTE", "SIN ESTADO",
}
```
