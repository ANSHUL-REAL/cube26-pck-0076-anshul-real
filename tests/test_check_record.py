"""`python -m pack_manager check-record`: a downloaded record, and its photos, checked on their own."""

import json

from conftest import make_order

import pack_manager.__main__ as cli
from pack_manager.evidence import apply_override
from pack_manager.models import Catalogue, CatalogueItem, Decision
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.vision.oracle import OraclePerceiver


def saved_record(tmp_path, sharp_photo, settings):
    catalogue = Catalogue(items=[CatalogueItem(sku="CAP-BLU", title="Blue Cap")])
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(make_order(("CAP-BLU", 1)), prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}),
                        settings, operator_label="op")
    record = apply_override(record, Decision.STOP_AND_FIX, "other", "op_b", note="lid torn")
    path = tmp_path / f"{record.record_id}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")  # as "Download record" saves it
    (tmp_path / "stored.jpg").write_bytes(prepared[0].jpeg)
    (tmp_path / "phone.jpg").write_bytes(sharp_photo)
    return path


def test_a_downloaded_record_and_its_photos_check_out(tmp_path, sharp_photo, settings, capsys):
    path = saved_record(tmp_path, sharp_photo, settings)
    code = cli.main(["check-record", str(path), "--photo", str(tmp_path / "stored.jpg"),
                     "--photo", str(tmp_path / "phone.jpg")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "OK   the record matches its content hash" in out
    assert "1 later hand decision all match" in out
    assert "is photo 1 (the stored copy)" in out and "is photo 1 (the original upload)" in out


def test_an_edited_record_or_another_photo_fails(tmp_path, sharp_photo, settings, capsys):
    path = saved_record(tmp_path, sharp_photo, settings)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["outcome"]["decision"] = "SEAL"  # someone flips the result in the file
    path.write_text(json.dumps(data), encoding="utf-8")
    other = tmp_path / "other.jpg"
    other.write_bytes(sharp_photo + b"x")
    assert cli.main(["check-record", str(path), "--photo", str(other)]) == 1
    out = capsys.readouterr().out
    assert "BAD  the record does not match its content hash" in out
    assert "is not one of this record's photos" in out


def test_not_a_record(tmp_path, capsys):
    bad = tmp_path / "x.json"
    bad.write_text("{}", encoding="utf-8")
    assert cli.main(["check-record", str(bad)]) == 2
