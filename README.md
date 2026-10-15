# TuCurul

**¿Quién me representa y cómo vota?** TuCurul es un proyecto de tecnología
cívica para México que busca responder dos preguntas a partir de dónde vives:

1. **Localización por sección electoral INE.** Con la entidad y la sección de
   tu credencial de elector, resolver tu distrito federal, distrito local y
   municipio, y de ahí a tus representantes: senadores, diputado federal y
   diputado local.
2. **Consolidación de fuentes.** Reunir en un solo perfil por legislador lo
   que hoy está disperso en múltiples portales: votaciones nominales,
   iniciativas presentadas y trayectoria administrativa.

## Arquitectura

```text
TuCurul/
├── data/
│   ├── states.csv              # 32 entidades: clave, nombre, distritos fed., senadores
│   ├── coverage.csv            # Matriz de cobertura de fuentes por entidad
│   ├── ine/
│   │   ├── secciones.csv       # Catálogo INE: entidad+sección → DF/DL/municipio
│   │   └── metadata.json       # Procedencia, sha256 del archivo, corte
│   └── raw/                    # Archivos descargados (no versionado)
├── src/tucurul/
│   ├── states.py               # Catálogo de entidades (State, load_states, get_state)
│   ├── coverage.py             # Matriz de cobertura (Status, score, tablas MD y HTML)
│   ├── limits.py               # Límites de tamaño (GitHub / política del proyecto)
│   ├── site.py                 # Generación del sitio estático (build_site)
│   ├── site_assets/            # index.html, app.js, lookup.js, style.css
│   ├── cli.py                  # CLI `tucurul` (states / coverage / ine-build / locate /
│   │                           #   build-site / check-sizes / update-readme)
│   ├── geo/
│   │   ├── dbf.py              # Lector DBF dBase III (stdlib, sin dependencias)
│   │   ├── ine.py              # Ingesta del Marco Geográfico Seccional del INE
│   │   └── seccion.py          # RepresentationKey + IneMarcoGeograficoLocator
│   └── sources/
│       ├── base.py             # Clase abstracta Source (name, url, levels, fetch)
│       ├── registry.py         # Registro de fuentes
│       └── …                   # Un módulo por fuente (stubs por ahora)
├── .github/workflows/pages.yml # CI + despliegue a GitHub Pages
└── tests/
```

## Fuentes planeadas

| Fuente | URL | Nivel | Qué aporta |
|---|---|---|---|
| SIL — Sistema de Información Legislativa (SEGOB) | <https://sil.gobernacion.gob.mx/> | Federal | Perfiles, iniciativas, votaciones, intervenciones |
| SITL / INFOPAL — Cámara de Diputados | <https://sitl.diputados.gob.mx/LXVI_leg/sistema_legislativo_LXVI.html> | Federal | Votaciones, asistencias, fichas, trabajo en comisiones |
| Senado — Votaciones | <https://senado.gob.mx/66/votaciones> | Federal | Votaciones plenarias y directorio por senador |
| Gaceta Parlamentaria | <https://gaceta.diputados.gob.mx/gp_inis.html> | Federal | Iniciativas de Diputados, legislaturas LVII–LXVI |
| Tequio | <https://tequio.app/> | Federal | Votaciones nominales, "Mis Representantes" |
| QuiénMeRepresenta | <https://www.quienmerepresenta.com.mx/> | Federal + estatal | Representantes por municipio o punto en el mapa |
| QuiénEsQuién.Wiki | <https://www.quienesquien.wiki/> | Los tres niveles | Trayectoria: funcionarios ↔ instituciones ↔ contratos |
| ONC — Observatorio Legislativo | <https://seguimientolegislativo.onc.org.mx/> | Federal + estatal | Votos en comisión, asistencias, currículos |

Para la localización por sección se usa el **Marco Geográfico Seccional
(MGS) del INE** ([SHAPEFILE.7z](https://cartografia.ine.mx/mapoteca/MGS_CCL/SHAPEFILE.7z);
véase también [Ubica tu casilla](https://ubicatucasilla.ine.mx/)), que
relaciona entidad + sección con distrito federal, distrito local y
municipio. El catálogo generado vive en `data/ine/secciones.csv`
(71,541 secciones; corte 2025-01-31). El INE publica productos nuevos
para el **Proceso Electoral 2026-2027 el 2026-11-12**: reconstruir el
catálogo con `tucurul ine-build` cuando salgan.

> Nota: la columna `municipio` del catálogo usa la **clave municipal del
> INE** (consecutiva por entidad), no la clave INEGI.

## Instalación

Requiere [uv](https://docs.astral.sh/uv/) y Python 3.12:

```bash
uv sync                  # crea .venv e instala el proyecto + dependencias de dev
uv sync --extra ingest   # además py7zr, para construir el catálogo INE
uv run pytest            # ejecuta las pruebas
uv run ruff check .      # lint
uv run tucurul states        # lista las 32 entidades
uv run tucurul coverage      # tabla de cobertura en Markdown
uv run tucurul update-readme # regenera la tabla de este README

# Catálogo INE (sección → distritos/municipio)
uv run tucurul ine-build                          # descarga el MGS a data/raw/
uv run tucurul ine-build --archive SHAPEFILE.7z   # o usa un archivo local
uv run tucurul locate 19 1234                     # Nuevo León, sección 1234
uv run tucurul locate CDMX 1                      # también acepta abreviaturas

# Sitio estático
uv run tucurul build-site       # genera ./site (index.html + data/*.json)
uv run tucurul check-sizes      # verifica límites de tamaño de data/
```

## Completitud de información por estado

La matriz en `data/coverage.csv` mide, para cada entidad, el estado de
consolidación de cada dimensión de información:

- **Sección→DF / Sección→DL**: mapeo de sección electoral a distrito federal / local.
- **Senadores / Dip. fed. / Dip. loc.**: directorios de representantes.
- **Votos fed. / Votos loc.**: votaciones nominales federales / locales.
- **Buscador OPLE**: buscador del organismo electoral estatal.

Las columnas **Secciones** y **Dist. loc.** se calculan del catálogo INE
(`data/ine/secciones.csv`); aparecen como "—" si el catálogo no se ha
generado. Cada celda tiene un peso: **ingestado** = 1.0, **fuente identificada** = 0.5,
**parcial** = 0.25, **sin fuente** = 0.0. La completitud es la media de los
pesos de sus dimensiones, en porcentaje.

<!-- coverage:start -->

| Clave | Estado | Dist. fed. | Secciones | Dist. loc. | Sección→DF | Sección→DL | Senadores | Dip. fed. | Votos fed. | Dip. loc. | Votos loc. | Buscador OPLE | Completitud | Notas |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01 | Aguascalientes | 3 | 685 | 18 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 02 | Baja California | 9 | 2155 | 17 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 03 | Baja California Sur | 2 | 525 | 16 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 04 | Campeche | 2 | 548 | 21 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 05 | Coahuila | 8 | 1789 | 16 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 06 | Colima | 2 | 406 | 16 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 07 | Chiapas | 13 | 2268 | 24 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 08 | Chihuahua | 9 | 3231 | 22 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 09 | Ciudad de México | 22 | 5579 | 33 | ✅ | ✅ | 🟡 | ✅ | ✅ | 🟡 | ⚠️ | ❌ | 65.6% | Congreso CDMX 'Ubica a tu diputado'; ONC cubre comisiones |
| 10 | Durango | 4 | 1390 | 15 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 11 | Guanajuato | 15 | 3266 | 22 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 12 | Guerrero | 8 | 2704 | 28 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 13 | Hidalgo | 7 | 1858 | 18 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 14 | Jalisco | 20 | 3905 | 20 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 15 | México | 40 | 6835 | 45 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ⚠️ | ❌ | 59.4% | ONC cubre comisiones del congreso Edomex |
| 16 | Michoacán | 11 | 2767 | 24 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 17 | Morelos | 5 | 945 | 12 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 18 | Nayarit | 3 | 1002 | 18 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 19 | Nuevo León | 14 | 2974 | 26 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | 🟡 | 62.5% | IEEPC NL votoinformado: sección -> distrito local + federal |
| 20 | Oaxaca | 10 | 2547 | 25 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 21 | Puebla | 16 | 2904 | 26 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 22 | Querétaro | 6 | 1007 | 15 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 23 | Quintana Roo | 4 | 1111 | 15 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 24 | San Luis Potosí | 7 | 1843 | 15 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 25 | Sinaloa | 7 | 3828 | 24 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 26 | Sonora | 7 | 1613 | 21 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 27 | Tabasco | 6 | 1185 | 21 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 28 | Tamaulipas | 8 | 2107 | 22 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 29 | Tlaxcala | 3 | 631 | 15 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 30 | Veracruz | 19 | 4963 | 30 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 31 | Yucatán | 6 | 1181 | 21 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| 32 | Zacatecas | 4 | 1789 | 18 | ✅ | ✅ | 🟡 | ✅ | ✅ | ❌ | ❌ | ❌ | 56.2% |  |
| **Σ** | **32 entidades** | **300** | **71541** | **679** | — | — | — | — | — | — | — | — | | |

**Senadores por entidad:** 96 (2 de mayoría relativa + 1 de primera minoría por entidad) + 32 de representación proporcional = **128 curules**.

**Leyenda:** ✅ datos ingeridos · 🟡 fuente identificada · ⚠️ cobertura parcial · ❌ sin fuente

<!-- coverage:end -->

## Sitio web

El sitio estático vive en
<https://dar4datascience.github.io/TuCurul/> y permite buscar tus distritos
con entidad + sección INE, además de mostrar la tabla de completitud.

```bash
uv run tucurul build-site               # genera ./site
python -m http.server -d site           # vista previa local en :8000
```

El despliegue corre en GitHub Actions (`.github/workflows/pages.yml`):
cada push a `main` (o `workflow_dispatch`) ejecuta lint, pruebas,
`check-sizes` y `build-site`, y publica el directorio `site/`.
Requiere **Settings → Pages → Source: "GitHub Actions"** en el repositorio.
Todas las rutas de recursos son relativas para funcionar bajo el subpath
`/TuCurul/`.

## Límites de tamaño

GitHub advierte sobre archivos >50 MiB, rechaza push de archivos >100 MiB y
limita las subidas web a 25 MiB. Umbrales del proyecto (`limits.py`):

- **Datos versionados** (`data/`, excluyendo `raw/`): máx. **25 MiB** por
  archivo — `tucurul check-sizes` falla si alguno lo excede, y
  `build_catalog` se rehúsa a escribir un `secciones.csv` más grande.
- **Sitio estático**: máx. **5 MiB** por archivo — `build_site` falla si
  alguna salida lo excede.

Tamaños actuales: `data/ine/secciones.csv` ≈ 2.1 MiB; el JSON por entidad más
grande es el del Estado de México (`data/secciones/15.json` ≈ 107 KiB); el
sitio completo pesa ≈ 1.2 MB.

## Datos y salvedades

- Los números de **distritos federales** en `data/states.csv` corresponden a
  la **distritación federal del INE 2023** y están **validados** contra el
  Marco Geográfico Seccional (corte 2025-01-31): el catálogo INE reproduce
  exactamente 300 distritos con los mismos conteos por entidad.
- Los **senadores** son 3 por entidad de mayoría relativa/primera minoría;
  los 32 de representación proporcional son nacionales y no aparecen en
  `states.csv`.

## Licencia

[GPLv3](LICENSE).
