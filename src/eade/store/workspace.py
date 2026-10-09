"""An EADE workspace: one project file holding the whole improvement cycle.

    campaign -> predictions -> corrections -> validation -> examples
             -> candidate version -> simulation -> evaluation -> publication

Every method takes the acting user and checks the permission it needs, so the
same rules apply whether the caller is the desktop app, the QGIS plugin or the
REST server. Every change is written to the audit log in the same transaction.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from ..core.decision import Candidate, Decision, Engine, Result
from ..core.evaluation import PublicationCriteria, Reference, compare_decisions, evaluate, judge
from ..core.knowledge import KnowledgeVersion, Status
from ..core.learning import Example, LearningOptions, build_candidate, split_for
from ..io import knowledge_json
from .schema import SCHEMA, SCHEMA_VERSION

PERMISSIONS = ("VIEW", "RUN", "REVIEW", "VALIDATE", "QUALITY", "PUBLISH", "ADMIN")
MODES = ("READ_ONLY", "COLLECT", "ADMIN")
REJECT_REASONS = {
    "1": "SLAB_OR_COURTYARD", "2": "VEGETATION", "3": "SHADOW", "4": "VEHICLE_OR_MOBILE",
    "5": "NEIGHBOUR", "6": "DUPLICATE", "7": "CONSTRUCTION_OR_RUIN", "8": "OTHER",
}
MAX_REDRAW_DISTANCE_M = 30.0
MANUAL_JUSTIFICATION_MIN = 15


# ------------------------------------------------------------------ errors

class EadeError(Exception):
    status = 400


class NotFound(EadeError):
    status = 404


class Forbidden(EadeError):
    status = 403


class Conflict(EadeError):
    status = 409


class Invalid(EadeError):
    status = 422


class Unavailable(EadeError):
    status = 503


@dataclass(frozen=True)
class Actor:
    name: str
    permissions: frozenset[str] = field(default_factory=lambda: frozenset(PERMISSIONS))

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise Forbidden(f"{self.name} lacks permission {permission}")


LOCAL = Actor("local")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=_json_default)


def _json_default(o: Any) -> Any:
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "wkt"):
        return o.wkt
    raise TypeError(type(o).__name__)


def _need_text(value: str | None, what: str = "a justification", minimum: int = 1) -> str:
    text = (value or "").strip()
    if len(text) < minimum:
        raise Invalid(f"{what} is required" + (f" ({minimum} characters at least)" if minimum > 1 else ""))
    return text


# ---------------------------------------------------------------- workspace

class Workspace:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(SCHEMA)
        with self._tx() as cur:
            cur.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            cur.execute("INSERT OR IGNORE INTO settings (id, updated_at, updated_by) VALUES (1, ?, 'system')",
                        (_now(),))
            # A campaign still RUNNING when the file is opened was cut off by a stop or a crash
            cur.execute("UPDATE campaigns SET status = 'INTERRUPTED' WHERE status = 'RUNNING'")

    @classmethod
    def create(cls, path: str | Path) -> "Workspace":
        p = Path(path)
        if p.exists():
            raise Conflict(f"{p} already exists")
        return cls(p)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._db.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                yield cur
            except BaseException:
                cur.execute("ROLLBACK")
                raise
            else:
                cur.execute("COMMIT")

    def _q(self, sql: str, args: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _one(self, sql: str, args: Sequence[Any] = (), what: str = "item") -> sqlite3.Row:
        rows = self._q(sql, args)
        if not rows:
            raise NotFound(f"{what} not found")
        return rows[0]

    @staticmethod
    def _audit(cur, actor: Actor, action: str, entity: str, entity_id: Any = None,
               justification: str | None = None, detail: Any = None) -> None:
        cur.execute("INSERT INTO audit (at, actor, action, entity, entity_id, justification, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_now(), actor.name, action, entity, None if entity_id is None else str(entity_id),
                     justification, None if detail is None else _j(detail)))

    # ============================================================ settings

    def settings(self) -> dict[str, Any]:
        return dict(self._one("SELECT * FROM settings WHERE id = 1"))

    def update_settings(self, actor: Actor, justification: str, **changes: Any) -> dict[str, Any]:
        actor.require("ADMIN")
        why = _need_text(justification)
        allowed = {"enabled", "mode", "min_iou_gain", "min_test_units"}
        unknown = set(changes) - allowed
        if unknown:
            raise Invalid(f"unknown settings: {', '.join(sorted(unknown))}")
        if "mode" in changes and changes["mode"] not in MODES:
            raise Invalid(f"mode must be one of {', '.join(MODES)}")
        if "enabled" in changes:
            changes["enabled"] = int(bool(changes["enabled"]))
        before = self.settings()
        with self._tx() as cur:
            for k, v in changes.items():
                cur.execute(f"UPDATE settings SET {k} = ? WHERE id = 1", (v,))
            cur.execute("UPDATE settings SET updated_at = ?, updated_by = ? WHERE id = 1", (_now(), actor.name))
            self._audit(cur, actor, "SETTINGS", "settings", 1, why,
                        {"before": {k: before[k] for k in changes}, "after": changes})
        return self.settings()

    def emergency_stop(self, actor: Actor, reason: str) -> dict[str, Any]:
        """Switch EADE off at once and cancel campaigns applying it. The classic engine carries on."""
        actor.require("ADMIN")
        why = _need_text(reason, "a reason")
        with self._tx() as cur:
            cur.execute("UPDATE settings SET enabled = 0, updated_at = ?, updated_by = ? WHERE id = 1",
                        (_now(), actor.name))
            cur.execute("UPDATE campaigns SET cancel_requested = 1 "
                        "WHERE eade_applied = 1 AND status IN ('PENDING', 'RUNNING', 'INTERRUPTED')")
            self._audit(cur, actor, "EMERGENCY_STOP", "settings", 1, why)
        return self.settings()

    # ============================================================ versions

    def versions(self) -> list[dict[str, Any]]:
        active = self.settings()["active_version"]
        rows = self._q("SELECT number, label, status, parent, fingerprint, publication, created_at, created_by, "
                       "published_at, published_by FROM versions ORDER BY number")
        return [{**dict(r), "active": r["number"] == active} for r in rows]

    def version(self, number: int) -> KnowledgeVersion:
        row = self._one("SELECT document FROM versions WHERE number = ?", (number,), f"version {number}")
        return knowledge_json.from_dict(json.loads(row["document"]), keep_status=True)

    def active_version(self) -> KnowledgeVersion | None:
        n = self.settings()["active_version"]
        return None if n is None else self.version(n)

    def next_version_number(self) -> int:
        return (self._q("SELECT COALESCE(MAX(number), 0) + 1 AS n FROM versions")[0]["n"])

    def _store_version(self, cur, actor: Actor, v: KnowledgeVersion) -> None:
        doc = _j(knowledge_json.to_dict(v))
        exists = cur.execute("SELECT status FROM versions WHERE number = ?", (v.number,)).fetchone()
        if exists is None:
            cur.execute("INSERT INTO versions (number, label, status, parent, fingerprint, document, publication, "
                        "created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (v.number, v.label, v.status.value, v.parent, v.fingerprint(), doc, v.publication,
                         _now(), actor.name))
        else:
            if exists["status"] in ("PUBLISHED", "ARCHIVED"):
                raise Conflict(f"version {v.number} is published and cannot change")
            cur.execute("UPDATE versions SET label = ?, status = ?, fingerprint = ?, document = ? WHERE number = ?",
                        (v.label, v.status.value, v.fingerprint(), doc, v.number))

    def save_draft(self, actor: Actor, version: KnowledgeVersion, justification: str) -> KnowledgeVersion:
        """Create or update a draft (rules, thresholds, weights...). Every change is justified."""
        actor.require("ADMIN")
        why = _need_text(justification)
        if version.frozen:
            raise Conflict("only a draft can be saved")
        with self._tx() as cur:
            self._store_version(cur, actor, version)
            self._audit(cur, actor, "VERSION_SAVE", "version", version.number, why,
                        {"fingerprint": version.fingerprint(), "rules": len(version.rules)})
        return version

    def new_draft(self, actor: Actor, from_number: int | None, label: str = "") -> KnowledgeVersion:
        actor.require("ADMIN")
        n = self.next_version_number()
        base = self.version(from_number) if from_number is not None else KnowledgeVersion(number=n, label="Initial")
        draft = base.new_draft(n, label or f"Draft from v{from_number}" if from_number else label or "Initial")
        with self._tx() as cur:
            self._store_version(cur, actor, draft)
            self._audit(cur, actor, "VERSION_CREATE", "version", n, None, {"from": from_number})
        return draft

    def import_version(self, actor: Actor, data: Mapping[str, Any]) -> KnowledgeVersion:
        """Import an exported file as a new draft. It must be evaluated here before publication."""
        actor.require("ADMIN")
        try:
            v = knowledge_json.from_dict(data)
        except (ValueError, KeyError) as e:
            raise Invalid(f"cannot import: {e}") from e
        n = self.next_version_number()
        v = v.new_draft(n, v.label, v.description)
        with self._tx() as cur:
            self._store_version(cur, actor, v)
            self._audit(cur, actor, "VERSION_IMPORT", "version", n, None,
                        {"fingerprint": v.fingerprint(), "original_number": data.get("number", data.get("numero"))})
        return v

    def export_version(self, number: int) -> dict[str, Any]:
        return knowledge_json.to_dict(self.version(number))

    def delete_draft(self, actor: Actor, number: int, justification: str) -> None:
        actor.require("ADMIN")
        why = _need_text(justification)
        if number == self.settings()["active_version"]:
            raise Conflict("the active version cannot be deleted")
        with self._tx() as cur:
            try:
                n = cur.execute("DELETE FROM versions WHERE number = ?", (number,)).rowcount
            except sqlite3.IntegrityError as e:
                raise Conflict(str(e)) from e
            if not n:
                raise NotFound(f"version {number} not found")
            self._audit(cur, actor, "VERSION_DELETE", "version", number, why)

    def publish(self, actor: Actor, number: int, justification: str, manual: bool = False) -> dict[str, Any]:
        """Freeze a version and make it active for new campaigns.

        An evaluated publication needs EADE on in ADMIN mode and an accepted
        evaluation of this exact fingerprint against the current active version.
        A manual publication skips those conditions; it needs a longer
        justification and is marked as such, with the state of its last evaluation.
        """
        actor.require("PUBLISH")
        why = _need_text(justification, minimum=MANUAL_JUSTIFICATION_MIN if manual else 1)
        v = self.version(number)
        if v.frozen:
            raise Conflict(f"version {number} is already {v.status.value}")
        s = self.settings()
        last = self._latest_evaluation(number)
        evaluation_state = ("NEVER_EVALUATED" if last is None
                            else "STALE" if last["fingerprint"] != v.fingerprint()
                            else "ACCEPTED" if last["accepted"] else "REFUSED")
        if not manual:
            if not s["enabled"] or s["mode"] != "ADMIN":
                raise Conflict("evaluated publication needs EADE enabled in ADMIN mode")
            if evaluation_state != "ACCEPTED":
                raise Conflict(f"no accepted evaluation of this exact version ({evaluation_state.lower()})")
            if last["baseline_number"] != s["active_version"]:
                raise Conflict("the evaluation was made against another active version: evaluate again")
        published = v.published("MANUAL" if manual else "EVALUATED")
        with self._tx() as cur:
            # one statement: once the row says PUBLISHED the database refuses any further change
            cur.execute("UPDATE versions SET status = ?, publication = ?, document = ?, fingerprint = ?, "
                        "published_at = ?, published_by = ? WHERE number = ?",
                        (published.status.value, published.publication, _j(knowledge_json.to_dict(published)),
                         published.fingerprint(), _now(), actor.name, number))
            cur.execute("UPDATE settings SET active_version = ?, updated_at = ?, updated_by = ? WHERE id = 1",
                        (number, _now(), actor.name))
            self._audit(cur, actor, "PUBLISH_MANUAL" if manual else "PUBLISH", "version", number, why,
                        {"fingerprint": v.fingerprint(), "previous_active": s["active_version"],
                         "evaluation": evaluation_state})
        return {"number": number, "publication": published.publication, "evaluation": evaluation_state}

    def rollback(self, actor: Actor, number: int, justification: str) -> dict[str, Any]:
        """Make an earlier published version active again. Past predictions keep their version."""
        actor.require("PUBLISH")
        why = _need_text(justification)
        v = self.version(number)
        if v.status is not Status.PUBLISHED:
            raise Conflict(f"version {number} is not published")
        previous = self.settings()["active_version"]
        with self._tx() as cur:
            cur.execute("UPDATE settings SET active_version = ?, updated_at = ?, updated_by = ? WHERE id = 1",
                        (number, _now(), actor.name))
            self._audit(cur, actor, "ROLLBACK", "version", number, why, {"previous_active": previous})
        return {"active_version": number, "previous": previous}

    # =========================================================== campaigns

    def create_campaign(self, actor: Actor, label: str, sources: Mapping[str, Any],
                        bounds: Sequence[float] | None = None, parcels: str | None = None,
                        parcel_id_field: str | None = None, apply_eade: bool = True) -> dict[str, Any]:
        """Register a detection campaign. The knowledge version is frozen now, at launch."""
        actor.require("RUN")
        if not (sources.get("dsm") or sources.get("ortho")):
            raise Invalid("a surface model (dsm) or an orthophoto is required")
        if self._q("SELECT 1 FROM campaigns WHERE status IN ('PENDING', 'RUNNING')"):
            raise Conflict("a campaign is already running")
        s = self.settings()
        applied = bool(apply_eade and s["enabled"] and s["active_version"] is not None)
        version = self.version(s["active_version"]) if applied else None
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO campaigns (label, status, eade_applied, mode, version_number, fingerprint, sources, "
                "bounds, parcels, parcel_id_field, created_at, created_by) "
                "VALUES (?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_need_text(label, "a label"), int(applied), s["mode"] if applied else None,
                 version.number if version else None, version.fingerprint() if version else None,
                 _j({k: sources.get(k) for k in ("dsm", "dtm", "ortho")}),
                 None if bounds is None else _j(list(bounds)), parcels, parcel_id_field, _now(), actor.name))
            cid = cur.lastrowid
            self._audit(cur, actor, "CAMPAIGN_CREATE", "campaign", cid, None,
                        {"eade_applied": applied, "version": version.number if version else None})
        return self.campaign(cid)

    def campaign(self, campaign_id: int) -> dict[str, Any]:
        row = dict(self._one("SELECT * FROM campaigns WHERE id = ?", (campaign_id,), f"campaign {campaign_id}"))
        for k in ("sources", "bounds", "provenance"):
            row[k] = json.loads(row[k]) if row[k] else None
        counts = {d: 0 for d in ("ACCEPTED", "REVIEW", "REJECTED")}
        for r in self._q("SELECT decision, COUNT(*) AS n FROM predictions WHERE campaign_id = ? GROUP BY decision",
                         (campaign_id,)):
            counts[r["decision"]] = r["n"]
        area = self._q("SELECT COALESCE(SUM(measure), 0) AS a FROM predictions "
                       "WHERE campaign_id = ? AND decision = 'ACCEPTED'", (campaign_id,))[0]["a"]
        row["counts"] = {**counts, "total": sum(counts.values()), "accepted_measure": round(area, 2)}
        row.pop("crs", None)
        return row

    def campaigns(self) -> list[dict[str, Any]]:
        return [self.campaign(r["id"]) for r in self._q("SELECT id FROM campaigns ORDER BY id DESC")]

    def cancel_campaign(self, actor: Actor, campaign_id: int) -> None:
        """Stop between two tiles. Predictions already written stay available."""
        actor.require("RUN")
        self.campaign(campaign_id)
        with self._tx() as cur:
            cur.execute("UPDATE campaigns SET cancel_requested = 1 WHERE id = ?", (campaign_id,))
            cur.execute("UPDATE campaigns SET status = 'CANCELLED', finished_at = ? "
                        "WHERE id = ? AND status IN ('PENDING', 'INTERRUPTED')", (_now(), campaign_id))
            self._audit(cur, actor, "CAMPAIGN_CANCEL", "campaign", campaign_id)

    def run_campaign(self, actor: Actor, campaign_id: int, detector: Any = None,
                     progress: Callable[[int, int], None] | None = None) -> dict[str, Any]:
        """Run (or resume) a campaign tile by tile. Each tile is written in its own transaction."""
        actor.require("RUN")
        from ..geo import HeightDetector, RasterSources, geo_catalog
        from ..geo.extract import ParcelIndex
        from ..geo.geometry import measure
        from ..geo.vector import read_features
        import shapely

        c = self.campaign(campaign_id)
        if c["status"] not in ("PENDING", "INTERRUPTED"):
            raise Conflict(f"campaign {campaign_id} is {c['status']}")
        version = self.version(c["version_number"]) if c["eade_applied"] else KnowledgeVersion(number=0)
        engine = Engine(version, geo_catalog())
        detector = detector or HeightDetector()
        src = RasterSources(**c["sources"])
        with self._tx() as cur:
            cur.execute("UPDATE campaigns SET status = 'RUNNING', started_at = COALESCE(started_at, ?), "
                        "error = NULL WHERE id = ?", (_now(), campaign_id))
            self._audit(cur, actor, "CAMPAIGN_RUN" if c["status"] == "PENDING" else "CAMPAIGN_RESUME",
                        "campaign", campaign_id)
        try:
            with src.open() as opened:
                crs = opened.crs
                index = None
                if c["parcels"]:
                    index = ParcelIndex((pid, g) for pid, g, _ in
                                        read_features(c["parcels"], crs, c["parcel_id_field"]))
                tiles = list(opened.tiles(tuple(c["bounds"]) if c["bounds"] else None,
                                          detector.params.tile_m, detector.params.overlap_m))
                done = {r["tile"] for r in self._q("SELECT tile FROM campaign_tiles WHERE campaign_id = ?",
                                                   (campaign_id,))}
                with self._tx() as cur:
                    cur.execute("UPDATE campaigns SET tiles_total = ?, crs = ?, provenance = ? WHERE id = ?",
                                (len(tiles), crs.to_wkt(), _j({
                                    "detector": detector.describe(), "sources": src.describe(),
                                    "knowledge": {"version": version.number, "fingerprint": engine.fingerprint},
                                    "resolution_m": opened.resolution}), campaign_id))
                for i, (window, core) in enumerate(tiles):
                    if i in done:
                        continue
                    if self._q("SELECT cancel_requested FROM campaigns WHERE id = ?", (campaign_id,))[0][0]:
                        with self._tx() as cur:
                            cur.execute("UPDATE campaigns SET status = 'CANCELLED', finished_at = ? WHERE id = ?",
                                        (_now(), campaign_id))
                        return self.campaign(campaign_id)
                    t0 = time.perf_counter()
                    patch = opened.read(window)
                    rows = []
                    for cand in detector.detect_tile(patch, core):
                        parcel_id = None
                        if index is not None:
                            ctx, parcel_id = index.context(cand.geometry)
                            cand = Candidate(cand.id, cand.target_class, {**cand.features, **ctx},
                                             cand.classic_accepted, cand.context, cand.geometry,
                                             {**cand.meta, "parcel_id": parcel_id})
                        r = engine.decide(cand)
                        g = cand.geometry
                        x0, y0, x1, y1 = g.bounds
                        rows.append((campaign_id, cand.id, cand.target_class, r.final_class, r.decision.value,
                                     r.score, None if cand.classic_accepted is None else int(cand.classic_accepted),
                                     cand.meta.get("classic_reason"),
                                     None if parcel_id is None else str(parcel_id), _j(dict(cand.features)),
                                     _j(r.explanation()), shapely.to_wkb(g), x0, y0, x1, y1, measure(g),
                                     version.number or None, engine.fingerprint if version.number else None,
                                     _now()))
                    with self._tx() as cur:
                        cur.executemany(
                            "INSERT OR IGNORE INTO predictions (campaign_id, candidate_id, class, final_class, "
                            "decision, score, classic_accepted, classic_reason, parcel_id, features, explanation, "
                            "geom, minx, miny, maxx, maxy, measure, version_number, fingerprint, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
                        cur.execute("INSERT INTO campaign_tiles VALUES (?, ?, ?, ?)",
                                    (campaign_id, i, len(rows), int((time.perf_counter() - t0) * 1000)))
                        cur.execute("UPDATE campaigns SET tiles_done = tiles_done + 1 WHERE id = ?", (campaign_id,))
                    done.add(i)
                    if progress is not None:
                        progress(len(done), len(tiles))
            with self._tx() as cur:
                cur.execute("UPDATE campaigns SET status = 'DONE', finished_at = ? WHERE id = ?",
                            (_now(), campaign_id))
        except Exception as e:
            with self._tx() as cur:
                cur.execute("UPDATE campaigns SET status = 'FAILED', error = ?, finished_at = ? WHERE id = ?",
                            (f"{type(e).__name__}: {e}", _now(), campaign_id))
            raise
        return self.campaign(campaign_id)

    # ========================================================= predictions

    def _crs(self, campaign_id: int) -> str | None:
        return self._one("SELECT crs FROM campaigns WHERE id = ?", (campaign_id,), "campaign")["crs"]

    @staticmethod
    def _prediction(row: sqlite3.Row, with_geometry: bool = True) -> dict[str, Any]:
        import shapely
        d = dict(row)
        d["features"] = json.loads(d["features"])
        d["explanation"] = json.loads(d["explanation"])
        d["classic_accepted"] = None if d["classic_accepted"] is None else bool(d["classic_accepted"])
        d["geometry"] = shapely.from_wkb(d.pop("geom")) if with_geometry else None
        for k in ("minx", "miny", "maxx", "maxy"):
            d.pop(k)
        return d

    def predictions(self, campaign_id: int, decision: str | None = None, parcel_id: str | None = None,
                    bbox: Sequence[float] | None = None, limit: int = 1000, offset: int = 0) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM predictions WHERE campaign_id = ?", [campaign_id]
        if decision:
            sql += " AND decision = ?"
            args.append(decision)
        if parcel_id is not None:
            sql += " AND parcel_id = ?"
            args.append(str(parcel_id))
        if bbox:
            sql += " AND maxx >= ? AND minx <= ? AND maxy >= ? AND miny <= ?"
            args += [bbox[0], bbox[2], bbox[1], bbox[3]]
        sql += " ORDER BY id LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [self._prediction(r) for r in self._q(sql, args)]

    def prediction(self, prediction_id: int) -> dict[str, Any]:
        return self._prediction(self._one("SELECT * FROM predictions WHERE id = ?", (prediction_id,),
                                          f"prediction {prediction_id}"))

    def measure(self, campaign_id: int, geometry: Any) -> dict[str, Any]:
        """Measure an outline drawn by an operator on the campaign's own rasters and parcels."""
        from ..geo import GeoFeatureExtractor, RasterSources
        from ..geo.extract import ParcelIndex
        from ..geo.vector import read_features

        c = self.campaign(campaign_id)
        try:
            with RasterSources(**c["sources"]).open() as src:
                features = GeoFeatureExtractor().measure(geometry, src)
                if c["parcels"]:
                    parcels = read_features(c["parcels"], src.crs, c["parcel_id_field"])
                    ctx, _ = ParcelIndex((pid, g) for pid, g, _ in parcels).context(geometry)
                    features.update(ctx)
        except OSError as e:
            raise Unavailable(f"the campaign rasters cannot be read: {e}") from e
        return features

    def crs_of(self, campaign_id: int):
        from pyproj import CRS
        wkt = self._crs(campaign_id)
        return CRS.from_wkt(wkt) if wkt else None

    # ============================================================== review

    def review_queue(self, campaign_id: int, order: str = "uncertainty", limit: int = 200) -> list[dict[str, Any]]:
        """Parcels to review. `uncertainty` first shows where the engine could not decide;
        `random` gives a sample that includes easy cases, the honest way to measure quality."""
        rows = self._q(
            "SELECT COALESCE(parcel_id, 'object:' || id) AS unit, "
            "SUM(status = 'TO_REVIEW') AS to_review, SUM(decision = 'REVIEW') AS undecided, "
            "MIN(ABS(COALESCE(score, 0.5) - 0.475)) AS closest, COUNT(*) AS objects "
            "FROM predictions WHERE campaign_id = ? AND decision <> 'REJECTED' "
            "GROUP BY unit HAVING to_review > 0", (campaign_id,))
        units = [dict(r) for r in rows]
        if order == "uncertainty":
            units.sort(key=lambda u: (-u["undecided"], u["closest"], u["unit"]))
        elif order == "random":
            import random
            random.Random(campaign_id).shuffle(units)
        elif order == "order":
            units.sort(key=lambda u: u["unit"])
        else:
            raise Invalid("order must be uncertainty, random or order")
        submitted = {r["parcel_id"]: r["n"] for r in self._q(
            "SELECT parcel_id, COUNT(*) AS n FROM corrections WHERE campaign_id = ? AND status = 'SUBMITTED' "
            "GROUP BY parcel_id", (campaign_id,))}
        for u in units:
            u["submitted"] = submitted.get(u["unit"], 0)
        return units[:limit]

    # ========================================================= corrections

    def corrections(self, campaign_id: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
        import shapely
        sql, args = "SELECT * FROM corrections WHERE 1 = 1", []
        if campaign_id is not None:
            sql += " AND campaign_id = ?"
            args.append(campaign_id)
        if status:
            sql += " AND status = ?"
            args.append(status)
        out = []
        for r in self._q(sql + " ORDER BY id", args):
            d = dict(r)
            for k in ("geom_before", "geom_after"):
                d[k] = shapely.from_wkb(d[k]) if d[k] is not None else None
            d["features_after"] = json.loads(d["features_after"]) if d["features_after"] else None
            out.append(d)
        return out

    def correct(self, actor: Actor, action: str, *, prediction_id: int | None = None, campaign_id: int | None = None,
                geometry: Any = None, class_after: str | None = None, reason: str | None = None,
                features: Mapping[str, Any] | None = None, parcel_id: str | None = None,
                group_id: str | None = None) -> dict[str, Any]:
        """Record a draft correction next to the prediction, which itself never changes.

        ACCEPT and REJECT judge a prediction; REDRAW and RECLASSIFY fix it; ADD
        records a missed object. Use split() and merge() for the other two.
        """
        actor.require("REVIEW")
        import shapely
        from ..geo.geometry import measure

        action = action.upper()
        pred = self.prediction(prediction_id) if prediction_id is not None else None
        if action != "ADD" and pred is None:
            raise Invalid(f"{action} needs a prediction")
        if pred is not None:
            campaign_id = pred["campaign_id"]
            parcel_id = pred["parcel_id"] if parcel_id is None else parcel_id
        if campaign_id is None:
            raise Invalid("campaign_id is required")
        self.campaign(campaign_id)
        if action == "REJECT":
            reason = REJECT_REASONS.get(str(reason), reason)
            if reason not in REJECT_REASONS.values():
                raise Invalid("a rejection needs a reason: " + ", ".join(f"{k} {v}" for k, v in REJECT_REASONS.items()))
        if action in ("REDRAW", "ADD", "SPLIT", "MERGE"):
            if geometry is None or geometry.is_empty or not geometry.is_valid:
                raise Invalid(f"{action} needs a valid geometry")
        if action == "REDRAW" and geometry.distance(pred["geometry"]) > MAX_REDRAW_DISTANCE_M:
            raise Invalid(f"the new outline is more than {MAX_REDRAW_DISTANCE_M:g} m away: record a missing object")
        if action in ("RECLASSIFY", "ADD") and not class_after:
            raise Invalid(f"{action} needs the class of the object")
        class_before = pred["final_class"] if pred else None
        if action in ("ACCEPT", "REDRAW", "SPLIT", "MERGE"):
            class_after = class_after or class_before
        with self._tx() as cur:
            if pred is not None and action not in ("SPLIT", "MERGE"):
                active = cur.execute("SELECT id, status, author FROM corrections WHERE prediction_id = ? "
                                     "AND status IN ('DRAFT', 'SUBMITTED', 'VALIDATED')", (prediction_id,)).fetchall()
                for a in active:
                    if a["status"] != "DRAFT" or a["author"] != actor.name:
                        raise Conflict(f"prediction {prediction_id} already has a {a['status'].lower()} correction")
                    cur.execute("DELETE FROM corrections WHERE id = ?", (a["id"],))
                cur.execute("UPDATE predictions SET status = 'IN_CORRECTION' WHERE id = ?", (prediction_id,))
            cur.execute(
                "INSERT INTO corrections (campaign_id, prediction_id, group_id, parcel_id, action, class_before, "
                "class_after, geom_before, geom_after, measure_before, measure_after, features_after, reason, "
                "author, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (campaign_id, prediction_id, group_id, None if parcel_id is None else str(parcel_id), action,
                 class_before, class_after if action != "REJECT" else None,
                 shapely.to_wkb(pred["geometry"]) if pred else None,
                 shapely.to_wkb(geometry) if geometry is not None else None,
                 pred["measure"] if pred else None, measure(geometry) if geometry is not None else None,
                 _j(dict(features)) if features else None, reason, actor.name, _now()))
            cid = cur.lastrowid
        return next(c for c in self.corrections(campaign_id) if c["id"] == cid)

    def split(self, actor: Actor, prediction_id: int, pieces: Sequence[Any],
              features: Sequence[Mapping[str, Any] | None] | None = None) -> list[dict[str, Any]]:
        """Two buildings were merged by the engine: one correction per resulting piece."""
        if len(pieces) < 2:
            raise Invalid("a split gives at least two pieces")
        group = uuid.uuid4().hex
        features = list(features or [None] * len(pieces))
        self._release_drafts(actor, [prediction_id])
        return [self.correct(actor, "SPLIT", prediction_id=prediction_id, geometry=g, features=f, group_id=group)
                for g, f in zip(pieces, features)]

    def merge(self, actor: Actor, prediction_ids: Sequence[int], geometry: Any,
              features: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """One building was cut into pieces: the merged outline replaces them all."""
        if len(prediction_ids) < 2:
            raise Invalid("a merge needs at least two predictions")
        group = uuid.uuid4().hex
        self._release_drafts(actor, prediction_ids)
        first = self.correct(actor, "MERGE", prediction_id=prediction_ids[0], geometry=geometry,
                             features=features, group_id=group)
        rest = [self.correct(actor, "MERGE", prediction_id=p, geometry=geometry, group_id=group)
                for p in prediction_ids[1:]]
        return [first, *rest]

    def _release_drafts(self, actor: Actor, prediction_ids: Sequence[int]) -> None:
        with self._tx() as cur:
            for p in prediction_ids:
                for a in cur.execute("SELECT id, status, author FROM corrections WHERE prediction_id = ? "
                                     "AND status IN ('DRAFT', 'SUBMITTED', 'VALIDATED')", (p,)).fetchall():
                    if a["status"] != "DRAFT" or a["author"] != actor.name:
                        raise Conflict(f"prediction {p} already has a {a['status'].lower()} correction")
                    cur.execute("DELETE FROM corrections WHERE id = ?", (a["id"],))

    def remove_draft(self, actor: Actor, correction_id: int) -> None:
        actor.require("REVIEW")
        row = self._one("SELECT * FROM corrections WHERE id = ?", (correction_id,), "correction")
        if row["status"] != "DRAFT" or row["author"] != actor.name:
            raise Conflict("only your own draft corrections can be removed")
        with self._tx() as cur:
            cur.execute("DELETE FROM corrections WHERE id = ?", (correction_id,))
            if row["prediction_id"] is not None and not cur.execute(
                    "SELECT 1 FROM corrections WHERE prediction_id = ?", (row["prediction_id"],)).fetchone():
                cur.execute("UPDATE predictions SET status = 'TO_REVIEW' WHERE id = ?", (row["prediction_id"],))

    def submit(self, actor: Actor, campaign_id: int, parcel_id: str | None = None) -> int:
        """Send the actor's drafts (of one parcel, or all) to the expert. They can no longer change."""
        actor.require("REVIEW")
        sql = "UPDATE corrections SET status = 'SUBMITTED', submitted_at = ? " \
              "WHERE campaign_id = ? AND author = ? AND status = 'DRAFT'"
        args: list[Any] = [_now(), campaign_id, actor.name]
        if parcel_id is not None:
            sql += " AND parcel_id = ?"
            args.append(str(parcel_id))
        with self._tx() as cur:
            n = cur.execute(sql, args).rowcount
            self._audit(cur, actor, "SUBMIT", "campaign", campaign_id, None, {"parcel": parcel_id, "corrections": n})
        return n

    def review(self, actor: Actor, correction_ids: Sequence[int], approve: bool, justification: str) -> dict[str, Any]:
        """Expert verdict on submitted corrections.

        A validated correction is final; in COLLECT or ADMIN mode it becomes
        learning material, filed in the train or test set by its 200 m cell.
        A rejected correction sends the object back to the review queue.
        """
        actor.require("VALIDATE")
        why = _need_text(justification)
        s = self.settings()
        learn = bool(s["enabled"]) and s["mode"] in ("COLLECT", "ADMIN")
        rows = [self._one("SELECT * FROM corrections WHERE id = ?", (i,), f"correction {i}") for i in correction_ids]
        for r in rows:
            if r["status"] != "SUBMITTED":
                raise Conflict(f"correction {r['id']} is {r['status'].lower()}, not submitted")
        examples = []
        if approve and learn:
            for r in rows:
                examples += self._examples_for(r, actor)
        with self._tx() as cur:
            for r in rows:
                cur.execute("UPDATE corrections SET status = ?, reviewer = ?, reviewed_at = ?, justification = ? "
                            "WHERE id = ?", ("VALIDATED" if approve else "REJECTED", actor.name, _now(), why, r["id"]))
                if r["prediction_id"] is not None:
                    cur.execute("UPDATE predictions SET status = ? WHERE id = ?",
                                ("VALIDATED" if approve else "TO_REVIEW", r["prediction_id"]))
            cur.executemany(
                "INSERT INTO examples (correction_id, campaign_id, class, polarity, classic_accepted, features, geom, "
                "cell, split, operator, validator, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", examples)
            self._audit(cur, actor, "VALIDATE" if approve else "REJECT_CORRECTIONS", "corrections",
                        ",".join(str(r["id"]) for r in rows), why, {"examples": len(examples)})
        return {"corrections": len(rows), "examples": len(examples), "learning": learn}

    def _examples_for(self, r: sqlite3.Row, actor: Actor) -> list[tuple]:
        """Learning material from one validated correction."""
        import shapely
        from ..geo.crs import grid_key

        crs = self._crs(r["campaign_id"])
        pred = self.prediction(r["prediction_id"]) if r["prediction_id"] is not None else None
        after = shapely.from_wkb(r["geom_after"]) if r["geom_after"] is not None else None
        feats_after = json.loads(r["features_after"]) if r["features_after"] else None
        items: list[tuple[str, str, Any, Any, Any]] = []  # class, polarity, features, classic, geometry
        a = r["action"]
        if a == "ACCEPT":
            items.append((pred["final_class"], "+", pred["features"], pred["classic_accepted"], pred["geometry"]))
        elif a == "REJECT":
            items.append((pred["class"], "-", pred["features"], pred["classic_accepted"], pred["geometry"]))
        elif a == "RECLASSIFY":
            items.append((pred["class"], "-", pred["features"], pred["classic_accepted"], pred["geometry"]))
            items.append((r["class_after"], "+", pred["features"], None, pred["geometry"]))
        elif a == "REDRAW":
            # the candidate was a true object; the reference outline is the redrawn one
            items.append((pred["class"], "+", pred["features"], pred["classic_accepted"], after))
        elif a in ("ADD", "SPLIT"):
            items.append((r["class_after"], "+", feats_after or {}, None, after))
        elif a == "MERGE":
            # every correction of the group carries the merged outline: keep it once
            first = self._q("SELECT MIN(id) AS i FROM corrections WHERE group_id = ?", (r["group_id"],))[0]["i"]
            if r["id"] == first:
                items.append((r["class_after"], "+", feats_after or {}, None, after))
        out = []
        for cls, pol, feats, classic, geom in items:
            if geom is None or not cls:
                continue
            cell = grid_key(geom, crs) if crs else f"campaign:{r['campaign_id']}"
            out.append((r["id"], r["campaign_id"], cls, pol, None if classic is None else int(classic),
                        _j(dict(feats)), shapely.to_wkb(geom), cell, split_for(cell),
                        r["author"], actor.name, _now()))
        return out

    # ===================================================== learning & quality

    def examples(self, split: str | None = None, with_geometry: bool = False) -> list[Example]:
        sql, args = "SELECT * FROM examples", []
        if split:
            sql += " WHERE split = ?"
            args.append(split)
        out = []
        for r in self._q(sql + " ORDER BY id", args):
            meta: dict[str, Any] = {"cell": r["cell"], "correction_id": r["correction_id"]}
            if with_geometry and r["geom"] is not None:
                import shapely
                meta["geometry"] = shapely.from_wkb(r["geom"])
            out.append(Example(str(r["id"]), r["class"], r["polarity"], json.loads(r["features"]),
                               None if r["classic_accepted"] is None else bool(r["classic_accepted"]),
                               r["split"], None, meta))
        return out

    def learning_summary(self) -> dict[str, Any]:
        rows = self._q("SELECT class, polarity, split, COUNT(*) AS n FROM examples GROUP BY class, polarity, split")
        return {"examples": [dict(r) for r in rows],
                "train": sum(r["n"] for r in rows if r["split"] == "TRAIN"),
                "test": sum(r["n"] for r in rows if r["split"] == "TEST")}

    def build_candidate(self, actor: Actor, base_number: int | None = None,
                        options: LearningOptions = LearningOptions()) -> tuple[KnowledgeVersion, dict[str, Any]]:
        """Learn a new draft from the training examples. Nothing is published."""
        actor.require("ADMIN")
        from ..geo import geo_catalog
        base = (self.version(base_number) if base_number is not None
                else self.active_version() or KnowledgeVersion(number=0, label="Empty"))
        n = self.next_version_number()
        candidate, report = build_candidate(base, self.examples("TRAIN"), geo_catalog(), n, options)
        candidate = candidate.evolve(status=Status.CANDIDATE)
        with self._tx() as cur:
            self._store_version(cur, actor, candidate)
            self._audit(cur, actor, "CANDIDATE_BUILD", "version", n, None, report.__dict__)
        return candidate, report.__dict__

    def _replay(self, campaign_id: int, version: KnowledgeVersion) -> list[Result]:
        from ..geo import geo_catalog
        engine = Engine(version, geo_catalog())
        out = []
        for p in self.predictions(campaign_id, limit=10 ** 9):
            cand = Candidate(str(p["id"]), p["class"], p["features"], p["classic_accepted"],
                             {"resolution_m": p["features"].get("resolution_m")}, p["geometry"],
                             {"parcel_id": p["parcel_id"]})
            out.append(engine.decide(cand))
        return out

    def simulate(self, actor: Actor, number: int, campaign_id: int) -> dict[str, Any]:
        """Replay a version (even a draft) on a campaign's stored candidates. Writes nothing but the audit line."""
        actor.require("QUALITY")
        c = self.campaign(campaign_id)
        reference = self.version(c["version_number"]) if c["eade_applied"] else KnowledgeVersion(number=0)
        summary = compare_decisions(self._replay(campaign_id, reference), self._replay(campaign_id, self.version(number)))
        with self._tx() as cur:
            self._audit(cur, actor, "SIMULATE", "version", number, None,
                        {"campaign": campaign_id, "changed": summary["changed"], "compared": summary["compared"]})
        return summary

    def evaluate(self, actor: Actor, number: int) -> dict[str, Any]:
        """Judge a version on the test cells, against the active version and the classic engine alone."""
        actor.require("QUALITY")
        from ..geo.crs import grid_key
        from ..geo.geometry import iou, measure

        version = self.version(number)
        tests = self.examples("TEST", with_geometry=True)
        cells = {e.meta["cell"] for e in tests}
        refs = [Reference(e.id, e.target_class, e.meta["geometry"]) for e in tests
                if e.polarity == "+" and "geometry" in e.meta]
        # the latest prediction of each candidate whose centre falls in a test cell
        latest: dict[str, dict[str, Any]] = {}
        for c in self._q("SELECT id, crs FROM campaigns WHERE crs IS NOT NULL ORDER BY id"):
            for p in self.predictions(c["id"], limit=10 ** 9):
                if grid_key(p["geometry"], c["crs"]) in cells:
                    latest[p["candidate_id"]] = p
        cands = [Candidate(str(p["id"]), p["class"], p["features"], p["classic_accepted"],
                           {"resolution_m": p["features"].get("resolution_m")}, p["geometry"])
                 for p in latest.values()]

        from ..geo import geo_catalog
        catalog = geo_catalog()

        def metrics(v: KnowledgeVersion):
            return evaluate(Engine(v, catalog).decide_all(cands), refs, iou, measure)

        s = self.settings()
        active = self.active_version()
        m_version = metrics(version)
        m_classic = metrics(KnowledgeVersion(number=0))
        m_active = metrics(active) if active is not None else m_classic
        verdict = judge(m_version, m_active, PublicationCriteria(s["min_iou_gain"], s["min_test_units"]))
        report = {"version": number, "fingerprint": version.fingerprint(),
                  "baseline": active.number if active else None, "test_cells": len(cells),
                  "candidates": len(cands), "verdict": verdict.to_dict(),
                  "classic": m_classic.to_dict(), "active": m_active.to_dict(), "evaluated": m_version.to_dict()}
        with self._tx() as cur:
            cur.execute("INSERT INTO evaluations (version_number, baseline_number, fingerprint, accepted, report, "
                        "created_at, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (number, s["active_version"], version.fingerprint(), int(verdict.accepted), _j(report),
                         _now(), actor.name))
            self._audit(cur, actor, "EVALUATE", "version", number, None,
                        {"accepted": verdict.accepted, "units": m_version.references})
        return report

    def _latest_evaluation(self, number: int) -> sqlite3.Row | None:
        rows = self._q("SELECT * FROM evaluations WHERE version_number = ? ORDER BY id DESC LIMIT 1", (number,))
        return rows[0] if rows else None

    def evaluations(self, number: int | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM evaluations", []
        if number is not None:
            sql += " WHERE version_number = ?"
            args.append(number)
        return [{**dict(r), "report": json.loads(r["report"]), "accepted": bool(r["accepted"])}
                for r in self._q(sql + " ORDER BY id DESC", args)]

    # =============================================================== audit

    def audit(self, limit: int = 200, offset: int = 0, action: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM audit", []
        if action:
            sql += " WHERE action = ?"
            args.append(action)
        rows = self._q(sql + " ORDER BY id DESC LIMIT ? OFFSET ?", [*args, limit, offset])
        return [{**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else None} for r in rows]

