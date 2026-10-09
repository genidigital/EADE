import pytest

from conftest import box_area, box_iou
from eade import (Candidate, Effect, Engine, KnowledgeVersion, PublicationCriteria, Reference, Rule,
                  compare_decisions, evaluate, judge)

REFS = [Reference("r1", "BUILDING", (0, 0, 10, 10)), Reference("r2", "BUILDING", (20, 0, 30, 10))]


def results(catalog, version, items):
    e = Engine(version, catalog)
    return [e.decide(Candidate(cid, "BUILDING", feats, classic_accepted=True, geometry=geom))
            for cid, geom, feats in items]


ITEMS = [
    ("a", (0, 0, 10, 9), {"height_m": 3}),       # matches r1, IoU 0.9
    ("b", (50, 50, 55, 55), {"height_m": 0.5}),  # a slab: false positive unless rejected
]


def test_object_level_metrics(catalog):
    m = evaluate(results(catalog, KnowledgeVersion(number=1), ITEMS), REFS, box_iou, box_area)
    b = m.by_class["BUILDING"]
    assert (b.true_positives, b.false_positives, b.misses) == (1, 1, 1)
    assert b.mean_iou == pytest.approx(0.9 / 3)
    assert b.precision == 0.5 and b.recall == 0.5
    # |90-100| + 25 (false positive) + 100 (miss), over 200 m² of reference
    assert b.relative_measure_error == pytest.approx(135 / 200)


def test_judge_requires_gain_without_regression(catalog):
    base_v = KnowledgeVersion(number=1)
    better_v = KnowledgeVersion(number=2, rules=(
        Rule("LOW", "BUILDING", Effect.REJECT, {"feature": "height_m", "op": "<", "value": 1}, weight=1,
             blocking=True),))
    base = evaluate(results(catalog, base_v, ITEMS), REFS, box_iou, box_area)
    better = evaluate(results(catalog, better_v, ITEMS), REFS, box_iou, box_area)
    assert better.mean_iou > base.mean_iou and better.false_positives == 0

    lenient = PublicationCriteria(min_test_units=2)
    assert judge(better, base, lenient).accepted
    assert not judge(base, better, lenient).accepted
    strict = judge(better, base, PublicationCriteria(min_test_units=20))
    assert not strict.accepted and strict.checks[0]["check"] == "test_units" and not strict.checks[0]["ok"]


def test_simulation_summary(catalog):
    before = results(catalog, KnowledgeVersion(number=1), ITEMS)
    after = results(catalog, KnowledgeVersion(number=2, rules=(
        Rule("LOW", "BUILDING", Effect.ABSTAIN, {"feature": "height_m", "op": "<", "value": 1}),)), ITEMS)
    s = compare_decisions(before, after)
    assert s["changed"] == 1 and s["transitions"] == {"ACCEPTED->ACCEPTED": 1, "ACCEPTED->REVIEW": 1}
    assert s["rule_hits"] == {"LOW": 1}
