"""EADE REST API and OGC API Features.

One server serves one workspace file. The QGIS plugin, the desktop app and any
other platform use the same endpoints. Geometries are exchanged as GeoJSON in
WGS 84 (RFC 7946) unless `crs=native` asks for the campaign's projected CRS.

Authentication: with a tokens file, every request carries
`Authorization: Bearer <token>`, mapped to a user and permissions. Without
one, the server runs in local mode with full rights and should only listen on
127.0.0.1.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from shapely.geometry import mapping, shape

from .. import __version__
from ..core.learning import LearningOptions
from ..geo import geo_catalog
from ..geo.crs import WGS84, reproject
from ..io import knowledge_json
from ..store import LOCAL, PERMISSIONS, Actor, EadeError, Invalid, NotFound, Workspace

API = "/api/v1"


# ------------------------------------------------------------------ models

class Justified(BaseModel):
    justification: str


class SettingsPatch(Justified):
    enabled: bool | None = None
    mode: Literal["READ_ONLY", "COLLECT", "ADMIN"] | None = None
    min_iou_gain: float | None = Field(None, ge=0, le=1)
    min_test_units: int | None = Field(None, ge=1)


class Reason(BaseModel):
    reason: str


class NewDraft(BaseModel):
    from_version: int | None = None
    label: str = ""


class SaveDraft(Justified):
    knowledge: dict[str, Any]


class Publish(Justified):
    manual: bool = False


class CampaignIn(BaseModel):
    label: str
    dsm: str | None = None
    dtm: str | None = None
    ortho: str | None = None
    bounds: list[float] | None = Field(None, min_length=4, max_length=4)
    parcels: str | None = None
    parcel_id_field: str | None = None
    apply_eade: bool = True
    start: bool = True


class CorrectionIn(BaseModel):
    action: Literal["ACCEPT", "REJECT", "REDRAW", "RECLASSIFY", "ADD"]
    prediction_id: int | None = None
    campaign_id: int | None = None
    geometry: dict[str, Any] | None = None
    class_after: str | None = None
    reason: str | None = None
    features: dict[str, Any] | None = None
    crs: Literal["wgs84", "native"] = "wgs84"


class SplitIn(BaseModel):
    prediction_id: int
    pieces: list[dict[str, Any]] = Field(min_length=2)
    crs: Literal["wgs84", "native"] = "wgs84"


class MergeIn(BaseModel):
    prediction_ids: list[int] = Field(min_length=2)
    geometry: dict[str, Any]
    crs: Literal["wgs84", "native"] = "wgs84"


class SubmitIn(BaseModel):
    parcel_id: str | None = None


class ReviewIn(Justified):
    ids: list[int] = Field(min_length=1)
    approve: bool


class SimulateIn(BaseModel):
    campaign_id: int


class CandidateIn(BaseModel):
    base_version: int | None = None
    signatures: bool = True
    recalibrate: bool = True
    thresholds: bool = True


# --------------------------------------------------------------------- app

def load_tokens(path: str | Path | None) -> dict[str, Actor] | None:
    """{"<token>": {"user": "name", "permissions": ["VIEW", ...]}} -> actors."""
    if not path:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for token, spec in raw.items():
        perms = frozenset(spec.get("permissions", ["VIEW"]))
        unknown = perms - set(PERMISSIONS)
        if unknown:
            raise ValueError(f"unknown permissions for {spec.get('user')}: {', '.join(sorted(unknown))}")
        out[token] = Actor(spec["user"], perms)
    return out


def create_app(workspace: Workspace | str | Path, tokens: dict[str, Actor] | None = None) -> FastAPI:
    ws = workspace if isinstance(workspace, Workspace) else Workspace(workspace)
    app = FastAPI(title="EADE", version=__version__,
                  description="Explainable, knowledge-driven and adaptive detection engine.")
    app.state.workspace = ws
    app.state.jobs: dict[int, threading.Thread] = {}

    @app.exception_handler(EadeError)
    async def _eade_error(_: Request, e: EadeError):
        return JSONResponse({"error": str(e)}, status_code=e.status)

    def actor(authorization: str | None = Header(None)) -> Actor:
        if tokens is None:
            return LOCAL
        if not authorization or not authorization.lower().startswith("bearer "):
            raise _Unauthorized("missing bearer token")
        a = tokens.get(authorization[7:].strip())
        if a is None:
            raise _Unauthorized("unknown token")
        return a

    @app.exception_handler(_Unauthorized)
    async def _unauthorized(_: Request, e: _Unauthorized):
        return JSONResponse({"error": str(e)}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    def view(a: Actor = Depends(actor)) -> Actor:
        a.require("VIEW")
        return a

    # ----------------------------------------------------------- geometry

    def to_native(campaign_id: int, geojson: dict[str, Any] | None, crs: str):
        if geojson is None:
            return None
        g = shape(geojson.get("geometry", geojson))
        return g if crs == "native" else reproject(g, WGS84, ws.crs_of(campaign_id))

    def feature(p: dict[str, Any], native_crs, native: bool) -> dict[str, Any]:
        g = p["geometry"] if native else reproject(p["geometry"], native_crs, WGS84)
        props = {k: v for k, v in p.items() if k not in ("geometry", "features", "explanation")}
        return {"type": "Feature", "id": p["id"], "geometry": mapping(g),
                "properties": {**props, "rules_fired": [r["code"] for r in p["explanation"]["rules_fired"]]}}

    def collection(campaign_id: int, preds: list[dict[str, Any]], native: bool) -> dict[str, Any]:
        crs = ws.crs_of(campaign_id)
        return {"type": "FeatureCollection", "numberReturned": len(preds),
                "features": [feature(p, crs, native) for p in preds]}

    # -------------------------------------------------------------- basics

    @app.get(f"{API}/health")
    def health():
        s = ws.settings()
        return {"status": "ok", "version": __version__, "workspace": ws.path.name,
                "eade": {"enabled": bool(s["enabled"]), "mode": s["mode"], "active_version": s["active_version"]},
                "auth": "tokens" if tokens is not None else "local"}

    @app.get(f"{API}/me")
    def me(a: Actor = Depends(view)):
        return {"user": a.name, "permissions": sorted(a.permissions)}

    @app.get(f"{API}/catalog")
    def catalog(_: Actor = Depends(view)):
        return geo_catalog().to_list()

    # ------------------------------------------------------------ settings

    @app.get(f"{API}/settings")
    def get_settings(_: Actor = Depends(view)):
        return ws.settings()

    @app.patch(f"{API}/settings")
    def patch_settings(body: SettingsPatch, a: Actor = Depends(actor)):
        changes = body.model_dump(exclude_none=True, exclude={"justification"})
        return ws.update_settings(a, body.justification, **changes)

    @app.post(f"{API}/settings/emergency-stop")
    def emergency_stop(body: Reason, a: Actor = Depends(actor)):
        return ws.emergency_stop(a, body.reason)

    # ------------------------------------------------------------ versions

    @app.get(f"{API}/versions")
    def versions(_: Actor = Depends(view)):
        return ws.versions()

    @app.get(f"{API}/versions/{{number}}")
    def get_version(number: int, _: Actor = Depends(view)):
        return ws.export_version(number)

    @app.post(f"{API}/versions", status_code=201)
    def new_version(body: NewDraft, a: Actor = Depends(actor)):
        return knowledge_json.to_dict(ws.new_draft(a, body.from_version, body.label))

    @app.put(f"{API}/versions/{{number}}")
    def save_version(number: int, body: SaveDraft, a: Actor = Depends(actor)):
        data = {**body.knowledge, "number": number}
        data.pop("fingerprint", None)
        try:
            v = knowledge_json.from_dict(data)
        except (ValueError, KeyError) as e:
            raise Invalid(f"invalid knowledge: {e}") from e
        problems = [p for r in v.rules for p in r.check(geo_catalog())]
        if problems:
            raise Invalid("; ".join(problems))
        return knowledge_json.to_dict(ws.save_draft(a, v, body.justification))

    @app.post(f"{API}/versions/import", status_code=201)
    def import_version(knowledge: dict[str, Any] = Body(...), a: Actor = Depends(actor)):
        return knowledge_json.to_dict(ws.import_version(a, knowledge))

    @app.delete(f"{API}/versions/{{number}}", status_code=204)
    def delete_version(number: int, justification: str = Query(...), a: Actor = Depends(actor)):
        ws.delete_draft(a, number, justification)

    @app.post(f"{API}/versions/{{number}}/publish")
    def publish(number: int, body: Publish, a: Actor = Depends(actor)):
        return ws.publish(a, number, body.justification, body.manual)

    @app.post(f"{API}/versions/{{number}}/rollback")
    def rollback(number: int, body: Justified, a: Actor = Depends(actor)):
        return ws.rollback(a, number, body.justification)

    @app.post(f"{API}/versions/{{number}}/simulate")
    def simulate(number: int, body: SimulateIn, a: Actor = Depends(actor)):
        return ws.simulate(a, number, body.campaign_id)

    @app.post(f"{API}/versions/{{number}}/evaluate")
    def evaluate(number: int, a: Actor = Depends(actor)):
        return ws.evaluate(a, number)

    @app.get(f"{API}/versions/{{number}}/evaluations")
    def evaluations(number: int, _: Actor = Depends(view)):
        return ws.evaluations(number)

    # ------------------------------------------------------------ learning

    @app.get(f"{API}/learning")
    def learning(_: Actor = Depends(view)):
        return ws.learning_summary()

    @app.post(f"{API}/learning/candidate", status_code=201)
    def candidate(body: CandidateIn, a: Actor = Depends(actor)):
        v, report = ws.build_candidate(a, body.base_version, LearningOptions(
            signatures=body.signatures, recalibrate=body.recalibrate, thresholds=body.thresholds))
        return {"version": knowledge_json.to_dict(v), "report": report}

    # ----------------------------------------------------------- campaigns

    def start(campaign_id: int, a: Actor) -> None:
        job = app.state.jobs.get(campaign_id)
        if job is not None and job.is_alive():
            return

        def work():
            try:
                ws.run_campaign(a, campaign_id)
            except Exception:  # the failure is recorded on the campaign row
                pass

        t = threading.Thread(target=work, name=f"eade-campaign-{campaign_id}", daemon=True)
        app.state.jobs[campaign_id] = t
        t.start()

    @app.get(f"{API}/campaigns")
    def campaigns(_: Actor = Depends(view)):
        return ws.campaigns()

    @app.post(f"{API}/campaigns", status_code=202)
    def create_campaign(body: CampaignIn, a: Actor = Depends(actor)):
        c = ws.create_campaign(a, body.label, {"dsm": body.dsm, "dtm": body.dtm, "ortho": body.ortho},
                               body.bounds, body.parcels, body.parcel_id_field, body.apply_eade)
        if body.start:
            start(c["id"], a)
        return c

    @app.get(f"{API}/campaigns/{{campaign_id}}")
    def get_campaign(campaign_id: int, _: Actor = Depends(view)):
        return ws.campaign(campaign_id)

    @app.post(f"{API}/campaigns/{{campaign_id}}/resume", status_code=202)
    def resume(campaign_id: int, a: Actor = Depends(actor)):
        a.require("RUN")
        start(campaign_id, a)
        return ws.campaign(campaign_id)

    @app.post(f"{API}/campaigns/{{campaign_id}}/cancel")
    def cancel(campaign_id: int, a: Actor = Depends(actor)):
        ws.cancel_campaign(a, campaign_id)
        return ws.campaign(campaign_id)

    @app.get(f"{API}/campaigns/{{campaign_id}}/predictions")
    def predictions(campaign_id: int, decision: str | None = None, parcel_id: str | None = None,
                    bbox: str | None = Query(None, description="xmin,ymin,xmax,ymax in the output CRS"),
                    crs: Literal["wgs84", "native"] = "wgs84", limit: int = Query(1000, le=10000), offset: int = 0,
                    _: Actor = Depends(view)):
        native = crs == "native"
        box_native = _bbox(bbox, None if native else ws.crs_of(campaign_id))
        preds = ws.predictions(campaign_id, decision, parcel_id, box_native, limit, offset)
        return collection(campaign_id, preds, native)

    @app.get(f"{API}/predictions/{{prediction_id}}")
    def prediction(prediction_id: int, crs: Literal["wgs84", "native"] = "wgs84", _: Actor = Depends(view)):
        p = ws.prediction(prediction_id)
        f = feature(p, ws.crs_of(p["campaign_id"]), crs == "native")
        f["properties"].update(features=p["features"], explanation=p["explanation"])
        return f

    @app.get(f"{API}/campaigns/{{campaign_id}}/queue")
    def queue(campaign_id: int, order: Literal["uncertainty", "random", "order"] = "uncertainty",
              limit: int = 200, _: Actor = Depends(view)):
        return ws.review_queue(campaign_id, order, limit)

    # --------------------------------------------------------- corrections

    def correction_out(c: dict[str, Any]) -> dict[str, Any]:
        crs = ws.crs_of(c["campaign_id"])
        out = {k: v for k, v in c.items() if k not in ("geom_before", "geom_after")}
        for k in ("geom_before", "geom_after"):
            out[k.replace("geom", "geometry")] = mapping(reproject(c[k], crs, WGS84)) if c[k] is not None else None
        return out

    @app.get(f"{API}/campaigns/{{campaign_id}}/corrections")
    def corrections(campaign_id: int, status: str | None = None, _: Actor = Depends(view)):
        return [correction_out(c) for c in ws.corrections(campaign_id, status)]

    @app.post(f"{API}/corrections", status_code=201)
    def correct(body: CorrectionIn, a: Actor = Depends(actor)):
        cid = body.campaign_id if body.campaign_id is not None else (
            ws.prediction(body.prediction_id)["campaign_id"] if body.prediction_id is not None else None)
        if cid is None:
            raise Invalid("campaign_id or prediction_id is required")
        geom = to_native(cid, body.geometry, body.crs)
        features = body.features
        if geom is not None and features is None:
            features = ws.measure(cid, geom)
        return correction_out(ws.correct(a, body.action, prediction_id=body.prediction_id, campaign_id=cid,
                                         geometry=geom, class_after=body.class_after, reason=body.reason,
                                         features=features))

    @app.post(f"{API}/corrections/split", status_code=201)
    def split(body: SplitIn, a: Actor = Depends(actor)):
        cid = ws.prediction(body.prediction_id)["campaign_id"]
        pieces = [to_native(cid, g, body.crs) for g in body.pieces]
        return [correction_out(c) for c in ws.split(a, body.prediction_id, pieces,
                                                    [ws.measure(cid, g) for g in pieces])]

    @app.post(f"{API}/corrections/merge", status_code=201)
    def merge(body: MergeIn, a: Actor = Depends(actor)):
        cid = ws.prediction(body.prediction_ids[0])["campaign_id"]
        g = to_native(cid, body.geometry, body.crs)
        return [correction_out(c) for c in ws.merge(a, body.prediction_ids, g, ws.measure(cid, g))]

    @app.delete(f"{API}/corrections/{{correction_id}}", status_code=204)
    def remove(correction_id: int, a: Actor = Depends(actor)):
        ws.remove_draft(a, correction_id)

    @app.post(f"{API}/campaigns/{{campaign_id}}/submit")
    def submit(campaign_id: int, body: SubmitIn, a: Actor = Depends(actor)):
        return {"submitted": ws.submit(a, campaign_id, body.parcel_id)}

    @app.post(f"{API}/corrections/review")
    def review(body: ReviewIn, a: Actor = Depends(actor)):
        return ws.review(a, body.ids, body.approve, body.justification)

    # --------------------------------------------------------------- audit

    @app.get(f"{API}/audit")
    def audit(limit: int = Query(200, le=1000), offset: int = 0, action: str | None = None,
              _: Actor = Depends(view)):
        return ws.audit(limit, offset, action)

    # ------------------------------------------------- OGC API Features

    def ogc_collection(c: dict[str, Any], base: str) -> dict[str, Any]:
        cid = f"campaign-{c['id']}"
        return {"id": cid, "title": c["label"], "itemType": "feature",
                "description": f"EADE predictions, campaign {c['id']} ({c['status'].lower()})",
                "links": [{"href": f"{base}/collections/{cid}/items", "rel": "items",
                           "type": "application/geo+json"}]}

    @app.get("/ogc")
    def ogc_landing(request: Request, _: Actor = Depends(view)):
        base = str(request.url).rstrip("/")
        return {"title": "EADE predictions", "links": [
            {"href": f"{base}/conformance", "rel": "conformance", "type": "application/json"},
            {"href": f"{base}/collections", "rel": "data", "type": "application/json"}]}

    @app.get("/ogc/conformance")
    def ogc_conformance():
        return {"conformsTo": ["http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
                               "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"]}

    @app.get("/ogc/collections")
    def ogc_collections(request: Request, _: Actor = Depends(view)):
        base = str(request.url).rsplit("/collections", 1)[0]
        return {"collections": [ogc_collection(c, base) for c in ws.campaigns() if c["status"] != "PENDING"],
                "links": []}

    @app.get("/ogc/collections/{collection_id}")
    def ogc_get_collection(collection_id: str, request: Request, _: Actor = Depends(view)):
        base = str(request.url).rsplit("/collections", 1)[0]
        return ogc_collection(ws.campaign(_campaign_of(collection_id)), base)

    @app.get("/ogc/collections/{collection_id}/items")
    def ogc_items(collection_id: str, bbox: str | None = None, limit: int = Query(100, le=10000),
                  offset: int = 0, _: Actor = Depends(view)):
        cid = _campaign_of(collection_id)
        preds = ws.predictions(cid, bbox=_bbox(bbox, ws.crs_of(cid)), limit=limit, offset=offset)
        out = collection(cid, preds, native=False)
        out["numberMatched"] = None
        return out

    return app


class _Unauthorized(Exception):
    pass


def _campaign_of(collection_id: str) -> int:
    if not collection_id.startswith("campaign-") or not collection_id[9:].isdigit():
        raise NotFound(f"collection {collection_id} not found")
    return int(collection_id[9:])


def _bbox(text: str | None, crs_of_campaign) -> list[float] | None:
    """Parse a bbox and bring it to the campaign CRS (it is in WGS 84 when `crs_of_campaign` is given)."""
    if not text:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError:
        raise Invalid("bbox must be xmin,ymin,xmax,ymax")
    if crs_of_campaign is None:
        return [x0, y0, x1, y1]
    from shapely.geometry import box
    return list(reproject(box(x0, y0, x1, y1), WGS84, crs_of_campaign).bounds)
