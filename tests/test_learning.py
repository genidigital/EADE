import random

import pytest

from eade import (NEGATIVE, POSITIVE, TEST, TRAIN, Effect, Example, KnowledgeVersion, LearningOptions, Rule,
                  Status, build_candidate, split_for)
from eade.core.learning import propose_thresholds, recalibrate


def examples(n_pos=40, n_neg=40, seed=7):
    rnd = random.Random(seed)
    out = []
    for i in range(n_pos):  # buildings: tall, square, not green
        out.append(Example(f"p{i}", "BUILDING", POSITIVE, {
            "height_m": rnd.uniform(2.6, 7), "rectangularity": rnd.uniform(0.75, 0.98),
            "green_share": rnd.uniform(0, 0.15), "area_m2": rnd.uniform(30, 300), "resolution_m": 0.02},
            classic_accepted=True))
    for i in range(n_neg):  # false positives: trees and slabs, low
        out.append(Example(f"n{i}", "BUILDING", NEGATIVE, {
            "height_m": rnd.uniform(0, 1.8), "rectangularity": rnd.uniform(0.3, 0.9),
            "green_share": rnd.uniform(0.05, 0.8), "area_m2": rnd.uniform(10, 200), "resolution_m": 0.02},
            classic_accepted=True))
    return out


def test_split_is_deterministic_and_about_one_in_five():
    keys = [f"32630:{x}:{y}" for x in range(40) for y in range(40)]
    test = [k for k in keys if split_for(k) == TEST]
    assert split_for(keys[0]) == split_for(keys[0])
    assert 0.15 < len(test) / len(keys) < 0.25


def test_recalibration_follows_precision(catalog):
    good = Rule("TALL", "BUILDING", Effect.CONFIRM, {"feature": "height_m", "op": ">=", "value": 2.5}, weight=0.3)
    bad = Rule("GREEN", "BUILDING", Effect.CONFIRM, {"feature": "green_share", "op": ">=", "value": 0.1})
    rules = recalibrate((good, bad), examples())
    tall, green = rules
    assert tall.stats["precision"] == 1.0 and tall.weight == 1.0
    assert green.stats["precision"] < 0.5 and green.active is False


def test_threshold_proposals_isolate_false_positives(catalog):
    proposals = propose_thresholds(examples(), catalog)
    assert proposals and all(r.effect is Effect.REJECT and r.origin == "LEARNED" for r in proposals)
    best = proposals[0]
    assert best.condition["feature"] == "height_m" and best.condition["op"] == "<"
    assert best.stats["precision"] >= 0.85
    assert not any(r.condition["feature"] == "resolution_m" for r in proposals)


def test_thresholds_need_enough_examples(catalog):
    assert propose_thresholds(examples(5, 5), catalog) == ()


def test_candidate_uses_train_only_and_never_touches_base(catalog):
    base = KnowledgeVersion(number=1, rules=(
        Rule("TALL", "BUILDING", Effect.CONFIRM, {"feature": "height_m", "op": ">=", "value": 2.5}, weight=0.3),
    )).published()
    exs = examples()
    held_out = [Example(e.id, e.target_class, e.polarity, e.features, e.classic_accepted, TEST) for e in exs[:10]]
    candidate, report = build_candidate(base, held_out + exs[10:], catalog, number=2)
    assert base.rules[0].weight == 0.3 and base.status is Status.PUBLISHED
    assert candidate.status is Status.DRAFT and candidate.parent == 1
    assert report.train_examples == len(exs) - 10
    assert {(s.target_class, s.polarity) for s in candidate.signatures} == {("BUILDING", "+"), ("BUILDING", "-")}
    assert any(r.origin == "LEARNED" for r in candidate.rules)
    # learning again replaces previous learned rules instead of piling them up
    again, _ = build_candidate(candidate, exs, catalog, number=3, options=LearningOptions(signatures=False))
    assert sum(r.origin == "LEARNED" for r in again.rules) == sum(r.origin == "LEARNED" for r in candidate.rules)
