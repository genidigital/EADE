# EADE architecture

EADE is one engine shipped in four forms. Everything shares the same core, the
same knowledge files and the same decisions: a version evaluated in the desktop
app gives exactly the same results inside QGIS or behind the REST API.

```text
                        ┌───────────────────────────────────────────┐
                        │ eade.core   (pure Python, no dependency)  │
                        │ features · rules · signatures · decision  │
                        │ knowledge versions · learning · evaluation│
                        └───────────────┬───────────────────────────┘
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              │                         │                          │
      eade.geo  (extra [geo])    eade.store                eade.server (extra [server])
      rasters, vectors, CRS,     projects, campaigns,      REST API, jobs,
      candidate detection,       predictions, corrections, OGC API Features
      33+ features, IoU,         audit (SQLite/GeoPackage
      200 m grid                 locally, PostGIS on servers)
              │                         │                          │
   ┌──────────┴─────────┬───────────────┴────────┬─────────────────┴─────────┐
   │                    │                        │                           │
 pip module        QGIS plugin            Desktop app (Windows setup)   Extensions
 `pip install      Processing             "EADE Studio": campaigns,      ArcGIS Pro toolbox,
  eade[geo]`       algorithms + review    review workshop, lab,          GeoServer / web map
 + `eade` CLI      dock in QGIS           knowledge editor               clients via REST/OGC
```

## Principles

- **The core has no dependency.** It must load inside QGIS, ArcGIS Pro, a frozen
  desktop executable or a server without conflicts. Heavy libraries (GDAL,
  rasterio, numpy, shapely) live in `eade.geo`, installed with the `[geo]` extra.
- **EADE judges, it does not draw.** A detection provider proposes candidates;
  EADE measures them, applies the active knowledge version and returns a
  decision with its explanation. Missed objects are added by people.
- **Knowledge is data.** Rules are JSON conditions, never code. Versions are
  fingerprinted (SHA-256 of everything that affects decisions); a published
  version is frozen and an imported one is always a draft.
- **Learning only from validated examples**, held-out test groups (one 200 m cell
  in five), and publication only after an evaluation that beats the active
  version without increasing false positives or measurement error.
- **Interoperability by standards**: GeoTIFF/COG, GeoPackage, GeoJSON, Shapefile
  through GDAL; OGC API Features for map servers and web clients.

## Delivery plan

| Phase | Deliverable | Status |
|---|---|---|
| 1 | `eade.core`: features, rule language, decision engine, signatures, knowledge versions and files (native + `eade-version/1` import), learning, evaluation, CLI | done |
| 2 | `eade.geo`: raster/vector I/O, CRS handling, tiling, candidate detection from DSM/DTM/orthophoto, feature extraction, IoU and measures, grid split | done |
| 3 | `eade.store` + `eade.server`: local project database, campaigns, corrections and audit; FastAPI REST API and jobs | done |
| 4 | QGIS plugin: Processing provider and review dock | next |
| 5 | EADE Studio desktop app (Qt) and Windows installer | planned |
| 6 | ArcGIS Pro toolbox, OGC API Features publication, ML provider interface | planned |

## Layout

```text
src/eade/
  core/        domain-agnostic engine
  io/          knowledge file formats
  geo/         geospatial adapter: rasters, vectors, detection, features
  store/       workspace file (.eade, SQLite): campaigns, predictions, corrections,
               examples, versions, evaluations, audit; guarantees enforced by triggers
  server/      REST API (/api/v1) and OGC API Features (/ogc)
  cli.py       `eade` command
tests/         pytest suite
docs/          landing page and design documents
```
