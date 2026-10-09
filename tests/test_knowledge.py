import json

import pytest

from eade import Effect, EngineConfig, FrozenVersionError, KnowledgeVersion, Rule, Status
from eade.io import knowledge_json


def rule(code="R1", **kw):
    return Rule(code, "BUILDING", Effect.CONFIRM, {"feature": "height_m", "op": ">=", "value": 2.5}, **kw)


def test_published_versions_are_frozen():
    v = KnowledgeVersion(number=2, rules=(rule(),)).published()
    assert v.status is Status.PUBLISHED and v.publication == "EVALUATED"
    with pytest.raises(FrozenVersionError):
        v.with_rule(rule("R2"))
    draft = v.new_draft(3)
    assert draft.status is Status.DRAFT and draft.parent == 2 and draft.rules == v.rules


def test_fingerprint_tracks_decisions_not_wording():
    v = KnowledgeVersion(number=1, rules=(rule(),))
    same = v.evolve(label="renamed", rules=(rule(label="Tall", rationale="why", stats={"support": 3}),))
    assert v.fingerprint() == same.fingerprint()
    assert v.fingerprint() != v.evolve(config=EngineConfig(accept_threshold=0.65)).fingerprint()
    assert v.fingerprint() != v.evolve(rules=(rule(weight=0.6),)).fingerprint()
    # 1 and 1.0 are the same number
    assert v.fingerprint() == KnowledgeVersion(number=9, rules=(rule(weight=0.5),)).fingerprint()


def test_rule_codes_unique_and_ordered():
    with pytest.raises(ValueError):
        KnowledgeVersion(number=1, rules=(rule(), rule()))
    v = KnowledgeVersion(number=1, rules=(rule("B", priority=20), rule("A", priority=20), rule("C", priority=5)))
    assert [r.code for r in v.rules] == ["C", "A", "B"]


def test_native_round_trip(tmp_path):
    v = KnowledgeVersion(number=4, label="x", rules=(rule(),)).published("MANUAL")
    path = tmp_path / "k.json"
    knowledge_json.save(v, path)
    imported = knowledge_json.load(path)
    assert imported.status is Status.DRAFT and imported.fingerprint() == v.fingerprint()
    assert knowledge_json.load(path, keep_status=True).publication == "MANUAL"


def test_tampered_file_is_refused(tmp_path):
    path = tmp_path / "k.json"
    knowledge_json.save(KnowledgeVersion(number=1, rules=(rule(),)), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"][0]["weight"] = 0.9
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(knowledge_json.KnowledgeFormatError, match="fingerprint"):
        knowledge_json.load(path)


LEGACY = {
    "format": "eade-version/1",
    "numero": 2,
    "statut": "PUBLIEE",
    "libelle": "Expert rules",
    "config": {
        "poids": {"cas": 1, "regles": 1, "hauteur": 0.5, "classique": 1},
        "seuils": {"ecarte": 0.3, "retenu": 0.65},
        "hauteur": {"BATIMENT": {"min": 2, "plein": 2.6}},
        "similarite": {"k": 5, "distance_max": 3, "effectif_min": 6},
    },
    "profils": [{"code": "DEFAUT", "libelle": "All", "sous_prefecture": None,
                 "resolution_min_m": None, "resolution_max_m": None}],
    "regles": [
        {"code": "EDGE", "libelle": "Cut by edge", "profil": None, "classe_cible": "BATIMENT", "effet": "ABSTENIR",
         "classe_resultat": None, "justification": "", "origine": "EXPERT",
         "conditions": {"ou": [{"op": "<", "car": "couverture_mns", "valeur": 0.7},
                               {"op": "=", "car": "tronque", "valeur": True}]},
         "poids": 0.5, "priorite": 40, "bloquante": False, "active": True, "statistiques": None},
        {"code": "TREE", "libelle": "", "profil": "DEFAUT", "classe_cible": "BATIMENT", "effet": "RECLASSER",
         "classe_resultat": "VEGETATION", "origine": "APPRENTISSAGE",
         "conditions": {"op": ">=", "car": "part_verte", "valeur": 0.5},
         "poids": 0.7, "priorite": 60, "bloquante": False, "active": True},
    ],
    "signatures": [],
}


def test_legacy_import():
    v = knowledge_json.from_dict(LEGACY)
    assert v.status is Status.DRAFT and v.number == 2
    assert (v.config.accept_threshold, v.config.reject_threshold) == (0.65, 0.3)
    assert v.config.similarity.min_count == 6
    (ramp,) = v.config.ramps
    assert (ramp.feature, ramp.low, ramp.full, ramp.classes) == ("hauteur_mediane_m", 2.0, 2.6, ("BATIMENT",))
    edge, tree = v.rules
    assert edge.effect is Effect.ABSTAIN and edge.condition["any"][1] == {"op": "=", "feature": "tronque", "value": True}
    assert tree.effect is Effect.RECLASSIFY and tree.origin == "LEARNED" and tree.profile is None
    assert v.profiles == ()


def test_unknown_format():
    with pytest.raises(knowledge_json.KnowledgeFormatError):
        knowledge_json.from_dict({"format": "other"})
