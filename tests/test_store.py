"""The full improvement cycle on a workspace file, on the synthetic survey."""

import sqlite3

import pytest

pytest.importorskip("eade.geo")

from shapely.geometry import box

from eade import Effect, Rule
from eade.geo import iou
from eade.store import LOCAL, Actor, Conflict, Forbidden, Invalid, Workspace
from synthetic import ANNEX, CAR, HOUSE, TREE_C, X0, Y0

PARCELS_NOTE = "parcels are optional; these tests run without them"


@pytest.fixture
def ws(tmp_path):
    w = Workspace.create(tmp_path / "project.eade")
    yield w
    w.close()


def sources(survey):
    return {k: str(survey[k]) for k in ("dsm", "dtm", "ortho")}


def run(ws, survey, label="Lot 1", **kw):
    c = ws.create_campaign(LOCAL, label, sources(survey), **kw)
    return ws.run_campaign(LOCAL, c["id"])


def find(preds, geom):
    return max(preds, key=lambda p: iou(p["geometry"], geom))


def test_defaults_and_settings_need_admin_and_justification(ws):
    s = ws.settings()
    assert (s["enabled"], s["mode"], s["active_version"]) == (0, "READ_ONLY", None)
    with pytest.raises(Invalid):
        ws.update_settings(LOCAL, "", enabled=True)
    with pytest.raises(Forbidden):
        ws.update_settings(Actor("op", frozenset({"VIEW", "REVIEW"})), "go", enabled=True)
    ws.update_settings(LOCAL, "pilot on Songon", enabled=True, mode="COLLECT")
    assert ws.audit(1)[0]["action"] == "SETTINGS"


def test_classic_campaign_and_database_guarantees(ws, survey):
    c = run(ws, survey)
    assert c["status"] == "DONE" and c["eade_applied"] == 0
    assert c["counts"] == {"ACCEPTED": 2, "REVIEW": 0, "REJECTED": 2, "total": 4,
                           "accepted_measure": pytest.approx(73, abs=3)}
    preds = ws.predictions(c["id"])
    house = find(preds, HOUSE)
    assert house["features"]["height_median_m"] == pytest.approx(4, abs=0.1)
    assert house["explanation"]["decision"] == "ACCEPTED"

    db = sqlite3.connect(ws.path)
    with pytest.raises(sqlite3.IntegrityError, match="cannot be modified"):
        db.execute("UPDATE predictions SET decision = 'REJECTED' WHERE id = ?", (house["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        db.execute("DELETE FROM predictions")
    with pytest.raises(sqlite3.IntegrityError, match="audit"):
        db.execute("DELETE FROM audit")
    db.close()


def test_one_campaign_at_a_time_and_interruption(ws, survey, tmp_path):
    c = ws.create_campaign(LOCAL, "first", sources(survey))
    with pytest.raises(Conflict):
        ws.create_campaign(LOCAL, "second", sources(survey))
    ws._db.execute("UPDATE campaigns SET status = 'RUNNING' WHERE id = ?", (c["id"],))
    ws.close()
    reopened = Workspace(tmp_path / "project.eade")
    assert reopened.campaign(c["id"])["status"] == "INTERRUPTED"
    assert reopened.run_campaign(LOCAL, c["id"])["status"] == "DONE"
    reopened.close()


def test_review_cycle_creates_examples_only_when_collecting(ws, survey):
    ws.update_settings(LOCAL, "collect", enabled=True, mode="COLLECT")
    c = run(ws, survey)
    preds = ws.predictions(c["id"])
    house, annex = find(preds, HOUSE), find(preds, ANNEX)
    tree = min(preds, key=lambda p: p["geometry"].centroid.distance(box(*TREE_C, *TREE_C)))

    queue = ws.review_queue(c["id"])
    assert len(queue) == 2  # rejected candidates are not queued

    op = Actor("operator", frozenset({"VIEW", "REVIEW"}))
    ws.correct(op, "ACCEPT", prediction_id=house["id"])
    with pytest.raises(Invalid, match="reason"):
        ws.correct(op, "REJECT", prediction_id=tree["id"])
    ws.correct(op, "REJECT", prediction_id=annex["id"], reason="1")
    ws.correct(op, "RECLASSIFY", prediction_id=tree["id"], class_after="VEGETATION")
    missed = box(X0 + 32, Y0 - 38, X0 + 37, Y0 - 34)
    ws.correct(op, "ADD", campaign_id=c["id"], geometry=missed, class_after="BUILDING",
               features={"area_m2": 20.0})
    with pytest.raises(Invalid, match="30 m"):
        ws.correct(op, "REDRAW", prediction_id=house["id"], geometry=box(X0 + 200, Y0, X0 + 201, Y0 + 1))
    assert ws.submit(op, c["id"]) == 4
    with pytest.raises(Conflict):
        ws.correct(op, "ACCEPT", prediction_id=house["id"])

    expert = Actor("expert", frozenset({"VIEW", "VALIDATE"}))
    submitted = [x["id"] for x in ws.corrections(c["id"], "SUBMITTED")]
    out = ws.review(expert, submitted, approve=True, justification="checked on the orthophoto")
    # ACCEPT 1, REJECT 1, RECLASSIFY 2 (negative building + positive vegetation), ADD 1
    assert out == {"corrections": 4, "examples": 5, "learning": True}
    exs = ws.examples()
    assert {(e.target_class, e.polarity) for e in exs} >= {("BUILDING", "+"), ("BUILDING", "-"), ("VEGETATION", "+")}
    assert all(e.split in ("TRAIN", "TEST") and e.meta["cell"].startswith("32630:") for e in exs)
    assert ws.prediction(house["id"])["status"] == "VALIDATED"
    with pytest.raises(sqlite3.IntegrityError):
        ws._db.execute("UPDATE corrections SET reason = 'x' WHERE id = ?", (submitted[0],))


def test_rejected_correction_goes_back_to_review_and_read_only_does_not_learn(ws, survey):
    ws.update_settings(LOCAL, "pilot", enabled=True, mode="READ_ONLY")
    c = run(ws, survey)
    house = find(ws.predictions(c["id"]), HOUSE)
    ws.correct(LOCAL, "REJECT", prediction_id=house["id"], reason="2")
    ws.submit(LOCAL, c["id"])
    (cid,) = [x["id"] for x in ws.corrections(c["id"], "SUBMITTED")]
    assert ws.review(LOCAL, [cid], approve=False, justification="it is a house")["examples"] == 0
    assert ws.prediction(house["id"])["status"] == "TO_REVIEW"
    ws.correct(LOCAL, "ACCEPT", prediction_id=house["id"])
    ws.submit(LOCAL, c["id"])
    (cid,) = [x["id"] for x in ws.corrections(c["id"], "SUBMITTED")]
    assert ws.review(LOCAL, [cid], approve=True, justification="ok") == {"corrections": 1, "examples": 0,
                                                                          "learning": False}


def test_versions_publication_rules_and_rollback(ws, survey):
    v1 = ws.new_draft(LOCAL, None, "Socle")
    with pytest.raises(Conflict, match="ADMIN mode"):
        ws.publish(LOCAL, v1.number, "go")
    with pytest.raises(Invalid, match="15 characters"):
        ws.publish(LOCAL, v1.number, "too short", manual=True)
    assert ws.publish(LOCAL, v1.number, "initial empty base", manual=True)["evaluation"] == "NEVER_EVALUATED"
    with pytest.raises(Conflict):
        ws.save_draft(LOCAL, ws.version(v1.number), "edit a published version")

    v2 = ws.new_draft(LOCAL, v1.number, "Low objects to review")
    v2 = v2.with_rule(Rule("LOW", "BUILDING", Effect.ABSTAIN, {"feature": "height_median_m", "op": "<", "value": 3.5}))
    ws.save_draft(LOCAL, v2, "annexes are often wrong")
    ws.update_settings(LOCAL, "pilot", enabled=True, mode="ADMIN")

    classic = run(ws, survey, "classic", apply_eade=False)
    sim = ws.simulate(LOCAL, v2.number, classic["id"])
    assert sim["changed"] == 1 and sim["transitions"]["ACCEPTED->REVIEW"] == 1

    report = ws.evaluate(LOCAL, v2.number)  # no validated test example yet
    assert report["verdict"]["accepted"] is False
    with pytest.raises(Conflict, match="refused"):
        ws.publish(LOCAL, v2.number, "go")

    ws.publish(LOCAL, v2.number, "expert rules for the pilot", manual=True)
    applied = run(ws, survey, "with v2")
    assert applied["eade_applied"] == 1 and applied["version_number"] == v2.number
    assert applied["counts"]["REVIEW"] == 1
    assert ws.rollback(LOCAL, v1.number, "v2 sends too much to review")["active_version"] == v1.number
    assert ws.prediction(find(ws.predictions(applied["id"]), ANNEX)["id"])["version_number"] == v2.number
    actions = [a["action"] for a in ws.audit()]
    assert {"PUBLISH_MANUAL", "ROLLBACK", "SIMULATE", "EVALUATE", "VERSION_SAVE"} <= set(actions)


def test_emergency_stop_and_import(ws, survey):
    from test_knowledge import LEGACY
    v = ws.import_version(LOCAL, LEGACY)
    assert v.status.value == "DRAFT" and v.number == 1 and len(v.rules) == 2
    ws.update_settings(LOCAL, "on", enabled=True, mode="COLLECT")
    ws.emergency_stop(LOCAL, "decisions look wrong")
    assert ws.settings()["enabled"] == 0
    with pytest.raises(Invalid):
        ws.emergency_stop(LOCAL, "")
