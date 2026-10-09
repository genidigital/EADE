"""Vector I/O through GDAL (pyogrio): GeoPackage, GeoJSON, Shapefile and the rest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pyogrio
import shapely
from shapely.geometry.base import BaseGeometry

from ..core.decision import Result
from .crs import reproject

_DRIVERS = {".gpkg": "GPKG", ".geojson": "GeoJSON", ".json": "GeoJSON", ".shp": "ESRI Shapefile",
            ".fgb": "FlatGeobuf"}


def driver_for(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext not in _DRIVERS:
        raise ValueError(f"unsupported vector format '{ext}': use one of {', '.join(sorted(_DRIVERS))}")
    return _DRIVERS[ext]


def read_features(path: str | Path, target_crs=None, id_field: str | None = None,
                  layer: str | int | None = None) -> list[tuple[Any, BaseGeometry, dict[str, Any]]]:
    """(id, geometry, properties) for every feature, reprojected to `target_crs` when given."""
    meta, fids, geoms, fields = pyogrio.raw.read(path, layer=layer, return_fids=True)
    names = list(meta["fields"])
    src_crs = meta.get("crs")
    out = []
    for i, wkb in enumerate(geoms):
        if wkb is None:
            continue
        g = shapely.from_wkb(wkb)
        if target_crs is not None and src_crs:
            g = reproject(g, src_crs, target_crs)
        props = {n: _py(fields[j][i]) for j, n in enumerate(names)}
        fid = props.get(id_field) if id_field else (int(fids[i]) if fids is not None else i)
        out.append((fid, g, props))
    return out


def _py(v: Any) -> Any:
    if isinstance(v, np.generic):
        return v.item()
    return v


def write_results(path: str | Path, results: Sequence[Result], crs, extra: Iterable[str] = ()) -> int:
    """Write decisions with their geometry. Returns the number of features written."""
    driver = driver_for(path)
    rows = [r for r in results if r.candidate.geometry is not None]
    extra = list(extra)
    columns: dict[str, list[Any]] = {k: [] for k in (
        "candidate_id", "class", "final_class", "decision", "score", "classic_accepted", "classic_reason",
        "rules_fired", "measure", "knowledge_version", "fingerprint", "explanation", *extra)}
    for r in rows:
        c = r.candidate
        columns["candidate_id"].append(c.id)
        columns["class"].append(c.target_class)
        columns["final_class"].append(r.final_class)
        columns["decision"].append(r.decision.value)
        columns["score"].append(np.nan if r.score is None else round(r.score, 4))
        columns["classic_accepted"].append(-1 if c.classic_accepted is None else int(c.classic_accepted))
        columns["classic_reason"].append(c.meta.get("classic_reason") or "")
        columns["rules_fired"].append(",".join(t.code for t in r.fired))
        columns["measure"].append(round(float(c.geometry.area if c.geometry.area else c.geometry.length), 3))
        columns["knowledge_version"].append(r.version)
        columns["fingerprint"].append(r.fingerprint)
        columns["explanation"].append(json.dumps(r.explanation(), ensure_ascii=False, default=_json_default))
        for k in extra:
            columns[k].append(_py(c.meta.get(k)) if c.meta.get(k) is not None else "")
    names = list(columns)
    data = [np.array(columns[n], dtype=_dtype(columns[n])) for n in names]
    geometry = np.array([shapely.to_wkb(r.candidate.geometry) for r in rows], dtype=object)
    Path(path).unlink(missing_ok=True)
    crs_str = crs.to_wkt() if hasattr(crs, "to_wkt") else str(crs)
    pyogrio.raw.write(str(path), geometry, data, names, crs=crs_str, driver=driver,
                      geometry_type="Unknown" if driver != "ESRI Shapefile" else "Polygon")
    return len(rows)


def _dtype(values: list[Any]):
    if values and all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) for v in values):
        return "int64"
    if values and all(isinstance(v, (int, float, np.number)) and not isinstance(v, bool) for v in values):
        return "float64"
    return object


def _json_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, BaseGeometry):
        return o.wkt
    raise TypeError(type(o).__name__)
