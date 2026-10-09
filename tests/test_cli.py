import json

from eade.cli import main
from eade.io import knowledge_json
from test_knowledge import LEGACY


def test_import_show_and_decide(tmp_path, capsys):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps(LEGACY), encoding="utf-8")
    native = tmp_path / "v2.json"
    assert main(["knowledge", "import", str(legacy), "-o", str(native)]) == 0
    assert knowledge_json.load(native).number == 2

    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([
        {"key": "couverture_mns", "label": "Elevation coverage"},
        {"key": "tronque", "type": "boolean", "label": "Cut by edge"},
        {"key": "part_verte", "label": "Green share"},
        {"key": "hauteur_mediane_m", "unit": "m"},
    ]), encoding="utf-8")
    capsys.readouterr()
    assert main(["knowledge", "show", str(native), "--catalog", str(catalog)]) == 0
    out = capsys.readouterr().out
    assert "IF Elevation coverage < 0.7 OR Cut by edge = yes" in out and "!" not in out

    cands = tmp_path / "c.jsonl"
    cands.write_text("\n".join(json.dumps(c) for c in [
        {"id": "1", "class": "BATIMENT", "classic_accepted": True, "features": {"hauteur_mediane_m": 3.1}},
        {"id": "2", "class": "BATIMENT", "classic_accepted": True, "features": {"tronque": True}},
    ]), encoding="utf-8")
    out_file = tmp_path / "out.jsonl"
    assert main(["decide", "--knowledge", str(native), "--catalog", str(catalog),
                 "--candidates", str(cands), "-o", str(out_file)]) == 0
    decisions = [json.loads(line)["decision"] for line in out_file.read_text(encoding="utf-8").splitlines()]
    assert decisions == ["ACCEPTED", "REVIEW"]


def test_errors_are_reported_not_raised(tmp_path, capsys):
    assert main(["knowledge", "show", str(tmp_path / "missing.json")]) == 2
    assert "eade:" in capsys.readouterr().err
