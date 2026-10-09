import pytest

from eade import (POSITIVE, NEGATIVE, Candidate, Decision, Effect, Engine, EngineConfig, KnowledgeVersion,
                  Profile, Ramp, Rule, Signature)

HEIGHT = Ramp("height", "height_m", low=2.0, full=2.6, weight=0.5, classes=("BUILDING",))


def version(*rules, **kw) -> KnowledgeVersion:
    return KnowledgeVersion(number=1, config=kw.pop("config", EngineConfig(ramps=(HEIGHT,))), rules=rules, **kw)


def cand(features, classic=True, **kw) -> Candidate:
    return Candidate(id=kw.pop("id", "c1"), target_class=kw.pop("target_class", "BUILDING"),
                     features=features, classic_accepted=classic, **kw)


def test_classic_only_follows_the_classic_engine(catalog):
    e = Engine(KnowledgeVersion(number=1), catalog)
    assert e.decide(cand({}, classic=True)).decision is Decision.ACCEPTED
    assert e.decide(cand({}, classic=False)).decision is Decision.REJECTED
    r = e.decide(cand({}, classic=None))
    assert r.decision is Decision.REVIEW and r.score is None and "NO_EVIDENCE" in r.guardrails


def test_weighted_mean_of_available_components(catalog):
    confirm = Rule("SQUARE", "BUILDING", Effect.CONFIRM, {"feature": "rectangularity", "op": ">=", "value": 0.8},
                   weight=0.6)
    e = Engine(version(confirm), catalog)
    r = e.decide(cand({"rectangularity": 0.9, "height_m": 2.3}, classic=False))
    # classic 0 (w1), rules 0.5 + 0.6/2 = 0.8 (w1), height (2.3-2)/0.6 = 0.5 (w0.5)
    assert r.components["rules"]["value"] == pytest.approx(0.8)
    assert r.components["height"]["value"] == pytest.approx(0.5)
    assert r.score == pytest.approx((0 + 0.8 + 0.25) / 2.5)
    assert r.decision is Decision.REVIEW


def test_missing_height_is_omitted_not_penalised(catalog):
    r = Engine(version(), catalog).decide(cand({"rectangularity": 0.9}))
    assert "height" not in r.components and r.score == 1.0


def test_classic_rejection_caps_at_review(catalog):
    strong = Rule("STRONG", "BUILDING", Effect.CONFIRM, {"feature": "height_m", "op": ">=", "value": 3}, weight=1)
    cfg = EngineConfig(classic_weight=0.1, ramps=(HEIGHT,))
    r = Engine(version(strong, config=cfg), catalog).decide(cand({"height_m": 4}, classic=False))
    assert r.score >= 0.6
    assert r.decision is Decision.REVIEW and "CLASSIC_REJECTED_CAPPED_AT_REVIEW" in r.guardrails


def test_abstain_blocking_and_reclassify(catalog):
    shadow = Rule("SHADOW", "BUILDING", Effect.ABSTAIN, {"feature": "shadow_share", "op": ">=", "value": 0.5},
                  priority=10)
    tree = Rule("TREE", "BUILDING", Effect.RECLASSIFY, {"feature": "green_share", "op": ">=", "value": 0.5},
                result_class="VEGETATION", priority=20)
    cars = Rule("CAR", "BUILDING", Effect.REJECT, {"feature": "area_m2", "op": "<", "value": 12},
                weight=0.3, blocking=True, priority=30)
    e = Engine(version(shadow, tree, cars), catalog)

    r = e.decide(cand({"shadow_share": 0.7, "area_m2": 80}))
    assert r.decision is Decision.REVIEW and r.guardrails == ("ABSTAIN_RULE:SHADOW",)

    r = e.decide(cand({"area_m2": 8, "height_m": 3}))
    assert r.decision is Decision.REJECTED and "BLOCKING_RULE:CAR" in r.guardrails

    r = e.decide(cand({"green_share": 0.8, "area_m2": 40}))
    assert r.final_class == "VEGETATION" and "RECLASSIFIED:TREE" in r.guardrails


def test_unknown_rules_are_reported(catalog):
    shadow = Rule("SHADOW", "BUILDING", Effect.ABSTAIN, {"feature": "shadow_share", "op": ">=", "value": 0.5})
    r = Engine(version(shadow), catalog).decide(cand({"area_m2": 50}))
    assert r.decision is Decision.ACCEPTED
    assert r.explanation()["rules_unknown"] == [{"code": "SHADOW", "missing": ["shadow_share"]}]


def test_similarity_component(catalog):
    pos = Signature("BUILDING", POSITIVE, {"rectangularity": 0.9, "height_m": 0.4, "green_share": 0.05},
                    {"rectangularity": 0.05, "height_m": 0.1, "green_share": 0.05}, count=30)
    neg = Signature("BUILDING", NEGATIVE, {"rectangularity": 0.5, "height_m": 0.05, "green_share": 0.6},
                    {"rectangularity": 0.2, "height_m": 0.05, "green_share": 0.2}, count=30)
    e = Engine(version(signatures=(pos, neg), config=EngineConfig()), catalog)
    house = e.decide(cand({"rectangularity": 0.92, "height_m": 4.0, "green_share": 0.03}, classic=None))
    tree = e.decide(cand({"rectangularity": 0.45, "height_m": 0.6, "green_share": 0.7}, classic=None))
    assert house.components["similarity"]["value"] > 0.8 and house.decision is Decision.ACCEPTED
    assert tree.components["similarity"]["value"] < 0.2 and tree.decision is Decision.REJECTED


def test_profile_specific_rules(catalog):
    p = Profile("COARSE", "Satellite imagery", {"resolution_m": {"min": 0.3}})
    r = Rule("COARSE_SMALL", "BUILDING", Effect.REJECT, {"feature": "area_m2", "op": "<", "value": 30},
             weight=1, blocking=True, profile="COARSE")
    e = Engine(version(r, profiles=(p,)), catalog)
    assert e.decide(cand({"area_m2": 20}, context={"resolution_m": 0.5})).decision is Decision.REJECTED
    assert e.decide(cand({"area_m2": 20}, context={"resolution_m": 0.05})).decision is Decision.ACCEPTED


def test_engine_refuses_invalid_rules(catalog):
    bad = Rule("BAD", "BUILDING", Effect.CONFIRM, {"feature": "unknown", "op": ">", "value": 1})
    with pytest.raises(ValueError, match="unknown feature"):
        Engine(version(bad), catalog)


def test_explanation_is_json_ready(catalog):
    import json
    r = Engine(version(), catalog).decide(cand({"height_m": 2.9}))
    data = json.loads(json.dumps(r.explanation()))
    assert data["knowledge"]["version"] == 1 and len(data["knowledge"]["fingerprint"]) == 64
