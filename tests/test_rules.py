import pytest

from eade import Effect, Rule, describe, validate
from eade.core.rules import MAX_DEPTH, RuleError, canonical, evaluate, features_used


def test_comparisons_and_kleene_logic():
    v = {"height_m": 3.2, "green_share": 0.1, "truncated": False}
    assert evaluate(canonical({"feature": "height_m", "op": ">=", "value": 2.5}), v) is True
    assert evaluate(canonical({"feature": "height_m", "between": [3, 4]}), v) is True
    assert evaluate(canonical({"feature": "truncated", "op": "=", "value": True}), v) is False
    missing = {"feature": "shadow_share", "op": ">", "value": 0.5}
    assert evaluate(canonical(missing), v) is None
    # FALSE dominates AND, TRUE dominates OR, otherwise UNKNOWN propagates
    assert evaluate(canonical({"all": [missing, {"feature": "height_m", "op": "<", "value": 1}]}), v) is False
    assert evaluate(canonical({"all": [missing, {"feature": "height_m", "op": ">", "value": 1}]}), v) is None
    assert evaluate(canonical({"any": [missing, {"feature": "height_m", "op": ">", "value": 1}]}), v) is True
    assert evaluate(canonical({"not": missing}), v) is None


def test_reads_record_consulted_values():
    reads = {}
    evaluate(canonical({"any": [{"feature": "a", "op": ">", "value": 1}, {"feature": "b", "in": ["x"]}]}),
             {"a": 2}, reads)
    assert reads == {"a": 2, "b": None}


def test_legacy_keys_are_accepted():
    legacy = {"et": [{"car": "height_m", "op": ">=", "valeur": 2}, {"non": {"car": "green_share", "entre": [0.5, 1]}}]}
    c = canonical(legacy)
    assert c == {"all": [{"feature": "height_m", "op": ">=", "value": 2},
                         {"not": {"feature": "green_share", "between": [0.5, 1]}}]}
    assert evaluate(c, {"height_m": 3, "green_share": 0.1}) is True


def test_validation_against_catalog(catalog):
    assert validate({"feature": "height_m", "op": ">=", "value": 2}, catalog) == []
    errors = validate({"all": [
        {"feature": "nope", "op": ">", "value": 1},
        {"feature": "height_m", "op": ">", "value": "tall"},
        {"feature": "truncated", "op": ">", "value": True},
        {"feature": "roof", "op": "<", "value": "metal"},
        {"feature": "area_m2", "op": "~", "value": 1},
        {"feature": "area_m2", "between": [5, 1]},
    ]}, catalog)
    assert len(errors) == 6


def test_depth_and_size_limits():
    node = {"feature": "x", "op": ">", "value": 0}
    for _ in range(MAX_DEPTH):
        node = {"not": node}
    assert any("deeper" in e for e in validate(node))
    wide = {"any": [{"feature": "x", "op": ">", "value": i} for i in range(60)]}
    assert any("nodes" in e for e in validate(wide))


def test_describe_uses_labels(catalog):
    text = describe({"all": [{"feature": "height_m", "op": ">=", "value": 2.5},
                             {"any": [{"feature": "truncated", "op": "=", "value": True},
                                      {"feature": "green_share", "op": "<", "value": 0.2}]}]}, catalog)
    assert text == "Height above ground >= 2.5 AND (Cut by survey edge = yes OR Green share < 0.2)"


def test_rule_invariants():
    with pytest.raises(RuleError):
        Rule("R", "BUILDING", Effect.CONFIRM, {"feature": "x", "op": ">", "value": 1}, weight=1.5)
    with pytest.raises(RuleError):
        Rule("R", "BUILDING", Effect.RECLASSIFY, {"feature": "x", "op": ">", "value": 1})
    r = Rule("R", "BUILDING", "REJECT", {"car": "x", "op": ">", "valeur": 1})
    assert r.effect is Effect.REJECT and r.condition == {"feature": "x", "op": ">", "value": 1}
    assert Rule.from_dict(r.to_dict()) == r
    assert features_used({"all": [{"feature": "a", "op": ">", "value": 1}, {"not": {"feature": "b", "in": [1]}}]}) == {"a", "b"}
