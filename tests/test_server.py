"""The REST API and OGC API Features, end to end on the synthetic survey."""

import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("rasterio")

from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from eade.geo.crs import WGS84, reproject
from eade.store import PERMISSIONS, Actor, Workspace
from synthetic import HOUSE, X0, Y0

from eade.server import create_app

TOKENS = {
    "t-admin": Actor("admin", frozenset(PERMISSIONS)),
    "t-op": Actor("operator", frozenset({"VIEW", "RUN", "REVIEW"})),
    "t-expert": Actor("expert", frozenset({"VIEW", "VALIDATE"})),
}
H = {name: {"Authorization": f"Bearer t-{name}"} for name in ("admin", "op", "expert")}


@pytest.fixture
def client(tmp_path):
    ws = Workspace.create(tmp_path / "p.eade")
    with TestClient(create_app(ws, TOKENS)) as c:
        yield c
    ws.close()


def wait_done(client, cid):
    for _ in range(200):
        c = client.get(f"/api/v1/campaigns/{cid}", headers=H["op"]).json()
        if c["status"] not in ("PENDING", "RUNNING"):
            return c
        time.sleep(0.05)
    raise AssertionError("campaign did not finish")


def wgs(geom):
    return mapping(reproject(geom, "EPSG:32630", WGS84))


def test_auth_and_permissions(client):
    assert client.get("/api/v1/health").json()["auth"] == "tokens"
    assert client.get("/api/v1/settings").status_code == 401
    assert client.get("/api/v1/settings", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/me", headers=H["op"]).json()["user"] == "operator"
    r = client.patch("/api/v1/settings", json={"justification": "x", "enabled": True}, headers=H["op"])
    assert r.status_code == 403 and "ADMIN" in r.json()["error"]
    r = client.patch("/api/v1/settings", json={"justification": "pilot", "enabled": True, "mode": "COLLECT"},
                     headers=H["admin"])
    assert r.status_code == 200 and r.json()["mode"] == "COLLECT"


def test_campaign_review_and_learning_over_http(client, survey):
    client.patch("/api/v1/settings", json={"justification": "pilot", "enabled": True, "mode": "COLLECT"},
                 headers=H["admin"])
    r = client.post("/api/v1/campaigns", headers=H["op"], json={
        "label": "Lot 1", "dsm": str(survey["dsm"]), "dtm": str(survey["dtm"]), "ortho": str(survey["ortho"])})
    assert r.status_code == 202
    c = wait_done(client, r.json()["id"])
    assert c["status"] == "DONE" and c["counts"]["total"] == 4

    fc = client.get(f"/api/v1/campaigns/{c['id']}/predictions", headers=H["op"]).json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 4
    lon, lat = fc["features"][0]["geometry"]["coordinates"][0][0]
    assert -4 < lon < -2 and 8 < lat < 10  # WGS 84 by default

    native = client.get(f"/api/v1/campaigns/{c['id']}/predictions?crs=native&decision=ACCEPTED",
                        headers=H["op"]).json()["features"]
    house = max(native, key=lambda f: f["properties"]["measure"])
    detail = client.get(f"/api/v1/predictions/{house['id']}", headers=H["op"]).json()
    assert detail["properties"]["explanation"]["decision"] == "ACCEPTED"

    # the operator redraws the house in WGS 84; the server measures the new outline itself
    redrawn = box(X0 + 5.1, Y0 - 14.9, X0 + 12.9, Y0 - 9.1)
    r = client.post("/api/v1/corrections", headers=H["op"],
                    json={"action": "REDRAW", "prediction_id": house["id"], "geometry": wgs(redrawn)})
    assert r.status_code == 201, r.text
    assert r.json()["features_after"]["height_median_m"] == pytest.approx(4, abs=0.15)
    missing = box(X0 + 32, Y0 - 38, X0 + 37, Y0 - 34)
    r = client.post("/api/v1/corrections", headers=H["op"], json={
        "action": "ADD", "campaign_id": c["id"], "geometry": mapping(missing), "crs": "native",
        "class_after": "BUILDING"})
    assert r.status_code == 201
    assert client.post(f"/api/v1/campaigns/{c['id']}/submit", json={}, headers=H["op"]).json() == {"submitted": 2}

    ids = [x["id"] for x in client.get(f"/api/v1/campaigns/{c['id']}/corrections?status=SUBMITTED",
                                       headers=H["expert"]).json()]
    r = client.post("/api/v1/corrections/review", headers=H["expert"],
                    json={"ids": ids, "approve": True, "justification": "matches the orthophoto"})
    assert r.json() == {"corrections": 2, "examples": 2, "learning": True}
    assert client.get("/api/v1/learning", headers=H["op"]).json()["train"] + \
        client.get("/api/v1/learning", headers=H["op"]).json()["test"] == 2

    r = client.post("/api/v1/learning/candidate", json={}, headers=H["admin"])
    assert r.status_code == 201 and r.json()["version"]["status"] == "CANDIDATE"
    n = r.json()["version"]["number"]
    sim = client.post(f"/api/v1/versions/{n}/simulate", json={"campaign_id": c["id"]}, headers=H["admin"])
    assert sim.status_code == 200 and sim.json()["compared"] == 4
    assert client.post(f"/api/v1/versions/{n}/evaluate", headers=H["admin"]).status_code == 200
    r = client.post(f"/api/v1/versions/{n}/publish", json={"justification": "go"}, headers=H["admin"])
    assert r.status_code == 409  # COLLECT mode, and nothing proves the gain yet
    audit = client.get("/api/v1/audit", headers=H["op"]).json()
    assert {"CAMPAIGN_CREATE", "SUBMIT", "VALIDATE", "CANDIDATE_BUILD", "EVALUATE"} <= {a["action"] for a in audit}


def test_versions_over_http(client):
    from test_knowledge import LEGACY
    r = client.post("/api/v1/versions/import", json=LEGACY, headers=H["admin"])
    assert r.status_code == 201 and r.json()["number"] == 1
    doc = client.get("/api/v1/versions/1", headers=H["op"]).json()
    doc["config"]["thresholds"]["accept"] = 0.7
    doc["rules"] = []
    r = client.put("/api/v1/versions/1", json={"knowledge": doc, "justification": "start clean"}, headers=H["admin"])
    assert r.status_code == 200 and r.json()["config"]["thresholds"]["accept"] == 0.7
    bad = {**doc, "rules": [{"code": "X", "target_class": "BUILDING", "effect": "CONFIRM",
                             "condition": {"feature": "nope", "op": ">", "value": 1}}]}
    r = client.put("/api/v1/versions/1", json={"knowledge": bad, "justification": "typo"}, headers=H["admin"])
    assert r.status_code == 422 and "unknown feature" in r.json()["error"]
    r = client.post("/api/v1/versions/1/publish", json={"justification": "base for the pilot", "manual": True},
                    headers=H["admin"])
    assert r.json()["publication"] == "MANUAL"
    assert client.put("/api/v1/versions/1", json={"knowledge": doc, "justification": "edit"},
                      headers=H["admin"]).status_code == 409
    assert [v["active"] for v in client.get("/api/v1/versions", headers=H["op"]).json()] == [True]


def test_ogc_api_features(client, survey):
    r = client.post("/api/v1/campaigns", headers=H["op"], json={
        "label": "Lot 1", "dsm": str(survey["dsm"]), "dtm": str(survey["dtm"]), "ortho": str(survey["ortho"])})
    wait_done(client, r.json()["id"])
    assert "ogcapi-features-1" in client.get("/ogc/conformance").json()["conformsTo"][0]
    cols = client.get("/ogc/collections", headers=H["op"]).json()["collections"]
    assert [c["id"] for c in cols] == ["campaign-1"]
    house_wgs = reproject(HOUSE, "EPSG:32630", WGS84).bounds
    items = client.get("/ogc/collections/campaign-1/items", headers=H["op"],
                       params={"bbox": ",".join(map(str, house_wgs))}).json()
    assert items["numberReturned"] == 1
    assert client.get("/ogc/collections/other/items", headers=H["op"]).status_code == 404
