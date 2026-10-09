"""Knowledge files.

Native format `eade.knowledge/1` (English keys). Importing also accepts the
`eade-version/1` exports of the first EADE integration (French keys), so an
existing knowledge base can be brought into the standalone engine.

An imported file is always a DRAFT: it has to be evaluated on the receiving
installation's own test set before it can be published there.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..core.knowledge import EngineConfig, KnowledgeVersion, Profile, Ramp, Status
from ..core.rules import Effect, Rule
from ..core.signatures import NEGATIVE, POSITIVE, Signature, SimilarityParams

FORMAT = "eade.knowledge/1"
LEGACY_FORMAT = "eade-version/1"


class KnowledgeFormatError(ValueError):
    pass


def to_dict(version: KnowledgeVersion) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "number": version.number,
        "label": version.label,
        "description": version.description,
        "status": version.status.value,
        "parent": version.parent,
        "publication": version.publication,
        "fingerprint": version.fingerprint(),
        "config": version.config.to_dict(),
        "profiles": [p.to_dict() for p in version.profiles],
        "rules": [r.to_dict() for r in version.rules],
        "signatures": [s.to_dict() for s in version.signatures],
    }


def from_dict(data: Mapping[str, Any], *, keep_status: bool = False) -> KnowledgeVersion:
    fmt = data.get("format")
    if fmt == LEGACY_FORMAT:
        return _from_legacy(data)
    if fmt != FORMAT:
        raise KnowledgeFormatError(f"unsupported knowledge format: {fmt!r}")
    version = KnowledgeVersion(
        number=int(data["number"]),
        label=data.get("label", ""),
        description=data.get("description", ""),
        status=Status(data.get("status", "DRAFT")) if keep_status else Status.DRAFT,
        parent=data.get("parent"),
        publication=data.get("publication") if keep_status else None,
        config=EngineConfig.from_dict(data.get("config")),
        profiles=tuple(Profile.from_dict(p) for p in data.get("profiles", ())),
        rules=tuple(Rule.from_dict(r) for r in data.get("rules", ())),
        signatures=tuple(Signature.from_dict(s) for s in data.get("signatures", ())),
    )
    stated = data.get("fingerprint")
    if stated and stated != version.fingerprint():
        raise KnowledgeFormatError("fingerprint mismatch: the file was modified after export")
    return version


def save(version: KnowledgeVersion, path: str | Path) -> None:
    Path(path).write_text(json.dumps(to_dict(version), ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: str | Path, *, keep_status: bool = False) -> KnowledgeVersion:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KnowledgeFormatError(f"{path}: not valid JSON ({e})") from e
    return from_dict(data, keep_status=keep_status)


# ---------------------------------------------------------------- legacy import

_EFFECTS = {"CONFIRMER": Effect.CONFIRM, "ECARTER": Effect.REJECT,
            "ABSTENIR": Effect.ABSTAIN, "RECLASSER": Effect.RECLASSIFY}
_ORIGINS = {"EXPERT": "EXPERT", "APPRENTISSAGE": "LEARNED"}
_POLARITY = {"POSITIF": POSITIVE, "NEGATIF": NEGATIVE, "+": POSITIVE, "-": NEGATIVE}
# The first integration measured height above ground under this key.
_LEGACY_HEIGHT_FEATURE = "hauteur_mediane_m"


def _from_legacy(d: Mapping[str, Any]) -> KnowledgeVersion:
    cfg = d.get("config") or {}
    poids = cfg.get("poids", {})
    seuils = cfg.get("seuils", {})
    sim = cfg.get("similarite", {})
    ramps = tuple(
        Ramp(name="height", feature=_LEGACY_HEIGHT_FEATURE, low=float(b["min"]), full=float(b["plein"]),
             weight=float(poids.get("hauteur", 0.5)), classes=(cls,))
        for cls, b in (cfg.get("hauteur") or {}).items()
    )
    base = SimilarityParams()
    config = EngineConfig(
        classic_weight=float(poids.get("classique", 1.0)),
        rules_weight=float(poids.get("regles", 1.0)),
        similarity_weight=float(poids.get("cas", 1.0)),
        ramps=ramps,
        accept_threshold=float(seuils.get("retenu", 0.6)),
        reject_threshold=float(seuils.get("ecarte", 0.35)),
        similarity=SimilarityParams(
            min_count=int(sim.get("effectif_min", base.min_count)),
            max_distance=float(sim.get("distance_max", base.max_distance)),
        ),
    )

    profiles = []
    for p in d.get("profils") or ():
        criteria: dict[str, Any] = {}
        if p.get("sous_prefecture") is not None:
            criteria["zone"] = p["sous_prefecture"]
        lo, hi = p.get("resolution_min_m"), p.get("resolution_max_m")
        if lo is not None or hi is not None:
            criteria["resolution_m"] = {k: v for k, v in (("min", lo), ("max", hi)) if v is not None}
        profiles.append(Profile(p["code"], p.get("libelle", ""), criteria))
    # A catch-all profile without criteria adds nothing: rules without profile already apply everywhere.
    general = {p.code for p in profiles if not p.criteria}
    profiles = [p for p in profiles if p.criteria]

    rules = []
    for r in d.get("regles") or ():
        effect = _EFFECTS.get(r.get("effet"))
        if effect is None:
            raise KnowledgeFormatError(f"rule {r.get('code')}: unknown effect {r.get('effet')!r}")
        profile = r.get("profil")
        rules.append(Rule(
            code=r["code"],
            label=r.get("libelle", ""),
            target_class=r["classe_cible"],
            effect=effect,
            result_class=r.get("classe_resultat"),
            condition=r["conditions"],
            weight=float(r.get("poids", 0.5)),
            priority=int(r.get("priorite", 100)),
            blocking=bool(r.get("bloquante", False)),
            active=bool(r.get("active", True)),
            rationale=r.get("justification", "") or "",
            origin=_ORIGINS.get(r.get("origine", "EXPERT"), "EXPERT"),
            profile=None if profile in general else profile,
            stats=r.get("statistiques"),
        ))

    signatures = []
    for s in d.get("signatures") or ():
        pol = _POLARITY.get(str(s.get("polarite", "")).upper())
        if pol is None:
            raise KnowledgeFormatError(f"signature: unknown polarity {s.get('polarite')!r}")
        profile = s.get("profil")
        signatures.append(Signature(
            target_class=s["classe"], polarity=pol, count=int(s["effectif"]),
            means={k: float(v) for k, v in s["moyennes"].items()},
            stds={k: float(v) for k, v in s["ecarts"].items()},
            profile=None if profile in general else profile,
        ))

    return KnowledgeVersion(
        number=int(d.get("numero", 1)),
        label=d.get("libelle", ""),
        description=d.get("description", ""),
        status=Status.DRAFT,
        config=config,
        profiles=tuple(profiles),
        rules=tuple(rules),
        signatures=tuple(signatures),
    )
