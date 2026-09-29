"""The eval scripts, the catalogue builder, the CLI and the model cache, without any network call.

GeminiPerceiver always gets a fake client here: the real (paid) model is never called.
"""

import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from conftest import make_order
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "catalogue"))

import build_catalogue  # noqa: E402
import common  # noqa: E402
import freeze  # noqa: E402
import import_photos  # noqa: E402
import make_label_sheet  # noqa: E402
import metrics  # noqa: E402
import run_eval  # noqa: E402

import pack_manager.__main__ as cli  # noqa: E402
from pack_manager.catalogue import select_candidates  # noqa: E402
from pack_manager.config import Settings  # noqa: E402
from pack_manager.pipeline import Photo, prepare_photos, verify_box  # noqa: E402
from pack_manager.vision import gemini  # noqa: E402
from pack_manager.vision.base import PerceptionError  # noqa: E402
from pack_manager.vision.oracle import OraclePerceiver  # noqa: E402

HEADER = "box_id,split,scenario,order_lines,actual_contents,conditions,notes\n"


@pytest.fixture
def eval_dir(tmp_path, monkeypatch):
    """A throwaway eval/ folder: the scripts never touch the repo's own."""
    d = tmp_path / "eval"
    (d / "labels").mkdir(parents=True)
    for mod in (common, metrics, freeze, run_eval, make_label_sheet, import_photos):
        monkeypatch.setattr(mod, "EVAL_DIR", d)
    monkeypatch.setattr(metrics, "LABEL_TIMES", {})
    return d


def write_photo(path: Path, value: int = 99) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((60, 80, 3), value, "uint8")).save(path)


# ---------------------------------------------------------------- manifest and labels

def test_manifest_saved_by_excel_with_a_bom_still_loads(eval_dir):
    rows = "T01,test,correct,CAP-BLU:1,CAP-BLU:1,window,\nT02,test,extra,CAP-BLU:1,CAP-BLU:1;X:1,\"lamp, hidden\",\n"
    (eval_dir / "manifest.csv").write_text(HEADER + rows, encoding="utf-8-sig")
    boxes = common.load_manifest("test")
    assert [b.box_id for b in boxes] == ["T01", "T02"]
    assert not boxes[0].hidden and boxes[1].hidden  # "hidden" after a comma counts too


def test_manifest_header_case_and_windows_1252(eval_dir):
    text = "Box ID,Split,Scenario,Order_Lines,Actual_Contents,Conditions,Notes\nT01,test,correct,CAP-BLU:1,CAP-BLU:1,,Café\n"
    (eval_dir / "manifest.csv").write_bytes(text.encode("cp1252"))
    [box] = common.load_manifest("test")
    assert box.box_id == "T01" and box.notes == "Café"


def test_label_time_without_timezone_is_read_as_utc(monkeypatch):
    monkeypatch.setattr(metrics, "LABEL_TIMES", {"A": ["2026-09-29T09:00:00.000Z"], "B": ["2026-09-29 09:00"]})
    assert metrics.labelled_before(["A", "B"], "2026-09-29T10:00:00+00:00") == "yes"
    assert metrics.labelled_before(["A", "B"], "2026-09-29T08:30:00+00:00").startswith("NO: A, B")
    metrics.LABEL_TIMES["B"] = ["29/09/2026 09:00"]
    assert metrics.labelled_before(["A", "B"], "2026-09-29T10:00:00+00:00").startswith("unknown (B:")


def test_two_label_files_with_the_same_name_are_refused(eval_dir):
    for name in ("a.csv", "b.csv"):
        (eval_dir / "labels" / name).write_text("labeller,box_id,decision,note,labelled_at\nRahul,T01,SEAL,,\n",
                                                encoding="utf-8")
    with pytest.raises(SystemExit, match="Rahul"):
        metrics.load_labels()


def test_kappa_is_undefined_when_everyone_gives_one_answer():
    assert metrics.cohen_kappa(["SEAL"] * 3, ["SEAL"] * 3, metrics.DECISIONS) is None
    assert metrics.cohen_kappa([], [], metrics.DECISIONS) is None
    assert metrics.kappa_text(None).startswith("n/a (undefined")
    assert metrics.cohen_kappa(["SEAL", "STOP_AND_FIX"], ["SEAL", "STOP_AND_FIX"], metrics.DECISIONS) == 1.0


class Quota:
    def perceive(self, *a):
        raise PerceptionError("429 quota")


class WithUsage(OraclePerceiver):
    def perceive(self, *a):
        return super().perceive(*a).model_copy(update={"usage": {"total_tokens": 5000}})


def test_report_skips_pending_tokens_and_has_no_blended_accuracy(eval_dir, catalogue, settings, sharp_photo,
                                                                 monkeypatch):
    (eval_dir / "manifest.csv").write_text(
        HEADER + "T01,test,correct,CAP-BLU:1,CAP-BLU:1,,\nT02,test,extra,CAP-BLU:1,CAP-BLU:1;CAP-RED:1,,\n",
        encoding="utf-8")
    run = eval_dir / "results" / "r1"
    (run / "records").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({
        "split": "test", "reveal_order": False, "model": "m", "match_threshold": 0.7, "visibility_threshold": 0.7,
        "started_at": "2026-09-29T10:00:00+00:00"}), encoding="utf-8")
    boxes = {b.box_id: b for b in common.load_manifest("test")}
    photos = prepare_photos([Photo(sharp_photo)], settings)
    answered = verify_box(boxes["T01"].order, photos, catalogue, WithUsage({"CAP-BLU": 1}), settings, operator_label="eval")
    pending = verify_box(boxes["T02"].order, photos, catalogue, Quota(), settings, operator_label="eval")
    (run / "records" / "T01.json").write_text(answered.model_dump_json(), encoding="utf-8")
    (run / "records" / "T02.json").write_text(pending.model_dump_json(), encoding="utf-8")
    # Both labellers said SEAL to everything (kappa undefined); one file was re-saved by Excel.
    (eval_dir / "labels" / "a.csv").write_text(
        "labeller,box_id,decision,note,labelled_at\nA,T01,SEAL,,2026-09-29T09:00:00.000Z\nA,T02,SEAL,,2026-09-29T09:01:00.000Z\n",
        encoding="utf-8")
    (eval_dir / "labels" / "b.csv").write_text(
        "labeller,box_id,decision,note,labelled_at\nB,T01,SEAL,,2026-09-29 09:00\nB,T02,SEAL,,2026-09-29 09:01\n",
        encoding="utf-8-sig")
    monkeypatch.setattr(sys, "argv", ["metrics.py", "--run", "r1"])
    metrics.main()

    m = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    assert m["tokens_per_box_mean"] == 5000 and m["boxes_with_token_counts"] == 1
    assert "accuracy_when_decided" not in m["box_decision"]
    assert m["humans"]["all_labels_made_before_the_agent_ran"] == "yes"
    assert m["humans"]["kappa_human_vs_human"] is None
    report = (run / "report.md").read_text(encoding="utf-8")
    assert "Accuracy when" not in report
    assert "kappa, human vs human: **n/a (undefined" in report


# ---------------------------------------------------------------- freeze

def test_freeze_sees_reference_photos_settings_and_eval_code(eval_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    (tmp_path / "pack_manager").mkdir()
    (tmp_path / "pack_manager" / "x.py").write_text("x = 1\n")
    (eval_dir / "run_eval.py").write_text("# eval code\n")
    (eval_dir / "manifest.csv").write_text(HEADER + "T01,test,correct,CAP-BLU:1,CAP-BLU:1,,\n", encoding="utf-8")
    write_photo(eval_dir / "boxes" / "T01" / "1.jpg")
    ref = tmp_path / "catalogue" / common.ORG / "images" / "CAP-BLU" / "1.jpg"
    write_photo(ref, 10)
    s = Settings(_env_file=None, gemini_api_key="fake-key-for-tests", session_secret="s3cret")
    frozen = json.loads(json.dumps(freeze.fingerprint("test", s)))  # as read back from the file

    assert freeze.differences(frozen, freeze.fingerprint("test", s)) == []
    assert "fake-key-for-tests" not in json.dumps(frozen) and "s3cret" not in json.dumps(frozen)

    write_photo(ref, 250)
    (eval_dir / "run_eval.py").write_text("# eval code, changed\n")
    changed = s.model_copy(update={"blur_min_var": 5000.0, "max_box_photos": 1})
    assert freeze.differences(frozen, freeze.fingerprint("test", changed)) == [
        "config: blur_min_var, max_box_photos",
        "code_sha256: eval/run_eval.py",
        f"catalogue_files_sha256: {common.ORG}/images/CAP-BLU/1.jpg",
    ]


def test_split_all_needs_the_test_freeze(eval_dir, monkeypatch):
    (eval_dir / "manifest.csv").write_text(
        HEADER + "D01,dev,correct,CAP-BLU:1,CAP-BLU:1,,\nT01,test,correct,CAP-BLU:1,CAP-BLU:1,,\n", encoding="utf-8")
    monkeypatch.setattr(run_eval, "eval_settings", lambda: Settings(_env_file=None))

    def no_model(*a, **k):
        raise AssertionError("the model must not be set up without a freeze")

    monkeypatch.setattr(run_eval, "GeminiPerceiver", no_model)
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--split", "all", "--run", "x"])
    with pytest.raises(SystemExit, match="--split all runs the test boxes"):
        run_eval.main()


# ---------------------------------------------------------------- label sheet and photo import

def test_label_sheet_shows_only_the_photos_the_agent_gets(eval_dir, monkeypatch):
    (eval_dir / "manifest.csv").write_text(HEADER + "T01,test,correct,CAP-BLU:1,CAP-BLU:1,,\n", encoding="utf-8")
    for n in range(1, 5):
        write_photo(eval_dir / "boxes" / "T01" / f"{n}.jpg", 40 * n)
    monkeypatch.setattr(make_label_sheet, "eval_settings", lambda: Settings(_env_file=None, max_box_photos=3))
    monkeypatch.setattr(sys, "argv", ["make_label_sheet.py", "--split", "test"])
    make_label_sheet.main()
    page = (eval_dir / "label_sheet_test.html").read_text(encoding="utf-8")
    assert page.count('alt="Box photo"') == 3
    assert "localStorage.setItem(keyFor(who)" in page  # answers are saved per labeller name


def test_import_fills_one_run_of_empty_boxes(eval_dir, tmp_path, monkeypatch, capsys):
    (eval_dir / "manifest.csv").write_text(
        HEADER + "".join(f"T0{i},test,correct,CAP-BLU:1,CAP-BLU:1,,\n" for i in range(1, 5)), encoding="utf-8")
    write_photo(eval_dir / "boxes" / "T02" / "1.jpg")  # T02 is done; T01, T03, T04 are not
    src = tmp_path / "phone"
    for n in range(3):
        write_photo(src / f"IMG_{n}.jpg", 30 * n)
    monkeypatch.setattr(sys, "argv", ["import_photos.py", "--from", str(src), "--split", "test", "--per-box", "1"])
    import_photos.main()
    out = capsys.readouterr().out
    assert "stopping before T02" in out
    assert "T01 " in out and "T03 " not in out  # never skips T02 and shifts T03 onto the next photos


def test_import_takes_the_whole_shoot_in_plan_order(eval_dir, tmp_path, monkeypatch):
    (eval_dir / "manifest.csv").write_text(
        HEADER + "D01,dev,correct,CAP-BLU:1,CAP-BLU:1,,\nD02,dev,missing,CAP-BLU:1,,,\n"
        "T01,test,correct,CAP-BLU:1,CAP-BLU:1,,\n", encoding="utf-8")
    src = tmp_path / "phone"
    for n in range(3):
        write_photo(src / f"IMG_{n}.jpg", 30 * n)
        os.utime(src / f"IMG_{n}.jpg", (1_790_000_000 + 60 * n,) * 2)
    monkeypatch.setattr(sys, "argv", ["import_photos.py", "--from", str(src), "--split", "all",
                                      "--per-box", "1", "--apply"])
    import_photos.main()
    # Each box gets the photo taken in its turn (the photos differ by brightness).
    got = [int(np.asarray(Image.open(eval_dir / "boxes" / b / "1.jpg"))[0, 0, 0]) for b in ("D01", "D02", "T01")]
    assert all(abs(v - want) <= 3 for v, want in zip(got, (0, 30, 60))), got


@pytest.mark.parametrize("save", [import_photos.save_clean, build_catalogue.save_clean])
def test_saved_copies_have_no_gps_exif_or_comment(tmp_path, save):
    src = tmp_path / "src.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees to display
    exif[0x8825] = {1: "N", 2: (28.0, 36.0, 0.0), 3: "E", 4: (77.0, 12.0, 0.0)}
    Image.fromarray(np.full((60, 80, 3), 90, "uint8")).save(src, "JPEG", exif=exif.tobytes(), comment=b"GPS 28.6N 77.2E")
    save(src, tmp_path / "clean.jpg", 1600)
    raw = (tmp_path / "clean.jpg").read_bytes()
    with Image.open(tmp_path / "clean.jpg") as img:
        assert img.size == (60, 80)  # upright
        assert len(img.getexif()) == 0 and "comment" not in img.info
    assert b"GPS 28.6N" not in raw


# ---------------------------------------------------------------- catalogue builder

def test_catalogue_accepts_excel_headers_and_encodings(tmp_path, monkeypatch):
    monkeypatch.setattr(build_catalogue, "HERE", tmp_path)
    org = tmp_path / "org_x"
    org.mkdir()
    (org / "products.csv").write_bytes("SKU, Title \nMUG-1,Café mug – white\n".encode("cp1252"))
    monkeypatch.setattr(sys, "argv", ["build_catalogue.py", "--org", "org_x"])
    build_catalogue.main()
    data = json.loads((org / "catalogue.json").read_text(encoding="utf-8"))
    assert [(i["sku"], i["title"]) for i in data["items"]] == [("MUG-1", "Café mug – white")]


def test_catalogue_with_no_readable_rows_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(build_catalogue, "HERE", tmp_path)
    org = tmp_path / "org_x"
    org.mkdir()
    (org / "catalogue.json").write_text('{"keep": true}', encoding="utf-8")
    (org / "products.csv").write_text("product,name\nMUG-1,Mug\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["build_catalogue.py", "--org", "org_x"])
    with pytest.raises(SystemExit, match="found: product, name"):
        build_catalogue.main()
    assert (org / "catalogue.json").read_text(encoding="utf-8") == '{"keep": true}'


# ---------------------------------------------------------------- model cache (fake client)

GOOD = {
    "objects": [{"object_id": "o1", "photo": 1, "box_2d": [10, 10, 500, 500], "description": "blue cap",
                 "classification": "CANDIDATE", "sku": "CAP-BLU", "confidence": 0.95, "alternative_skus": [],
                 "deciding_feature": "blue", "partially_hidden": False}],
    "counts": [{"sku": "CAP-BLU", "count": 1, "count_certain": True, "reason": ""}],
    "scene": {"box_interior_fully_visible": True, "items_may_be_hidden": False, "visibility_confidence": 0.95,
              "notes": ""},
    "image_issues": [],
}


class FakeModels:
    def __init__(self):
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=20, thoughts_token_count=0,
                                total_token_count=120)
        return SimpleNamespace(text=json.dumps(GOOD), usage_metadata=usage, model_version="fake-model")


@pytest.fixture
def fake_gemini(tmp_path, monkeypatch):
    """Returns make(settings_update) -> (perceiver, fake models). No network is ever used."""
    def make(**update):
        models = FakeModels()
        monkeypatch.setattr(gemini, "genai", SimpleNamespace(Client=lambda **kw: SimpleNamespace(models=models)))
        s = Settings(_env_file=None, gemini_api_key="fake-key-for-tests", cache_dir=str(tmp_path / "cache"), **update)
        return gemini.GeminiPerceiver(s), models
    return make


def test_cache_key_changes_with_inserts_and_thinking_budget(fake_gemini, catalogue, settings, sharp_photo):
    photos = prepare_photos([Photo(sharp_photo)], settings)
    cands = select_candidates(make_order(("CAP-BLU", 1)), catalogue, settings)

    p, models = fake_gemini()
    assert not p.perceive(photos, cands, ["packing slip"], None).cached
    p, models = fake_gemini()
    assert p.perceive(photos, cands, ["packing slip"], None).cached and models.calls == 0
    p, models = fake_gemini()
    assert not p.perceive(photos, cands, ["packing slip", "loose cable"], None).cached and models.calls == 1
    p, models = fake_gemini(gemini_thinking_budget=2048)
    assert not p.perceive(photos, cands, ["packing slip"], None).cached and models.calls == 1


def test_broken_cache_file_is_replaced_by_a_fresh_call(fake_gemini, catalogue, settings, sharp_photo, tmp_path):
    photos = prepare_photos([Photo(sharp_photo)], settings)
    order = make_order(("CAP-BLU", 1))
    p, models = fake_gemini()
    verify_box(order, photos, catalogue, p, settings, operator_label="op")
    [cache_file] = (tmp_path / "cache").glob("*.json")

    cache_file.write_text('{"text": "{\\"objects\\": [', encoding="utf-8")  # cut short by a crash
    p, models = fake_gemini()
    rec = verify_box(order, photos, catalogue, p, settings, operator_label="op")
    assert models.calls == 1 and rec.outcome.decision.value != "PENDING"
    assert json.loads(cache_file.read_text(encoding="utf-8"))["model_version"] == "fake-model"
    assert sorted(f.name for f in (tmp_path / "cache").iterdir()) == [cache_file.name]  # no temp files left

    p, models = fake_gemini()
    assert verify_box(order, photos, catalogue, p, settings, operator_label="op").observations["cached_response"]
    assert models.calls == 0


# ---------------------------------------------------------------- CLI

@pytest.fixture
def cli_files(tmp_path, catalogue, sharp_photo):
    (tmp_path / "catalogue.json").write_text(catalogue.model_dump_json(), encoding="utf-8")
    (tmp_path / "order.json").write_text(make_order(("CAP-BLU", 1)).model_dump_json(), encoding="utf-8")
    (tmp_path / "box.jpg").write_bytes(sharp_photo)
    return ["verify", "--catalogue", str(tmp_path), "--order", str(tmp_path / "order.json"),
            "--photo", str(tmp_path / "box.jpg"), "--out", str(tmp_path / "rec.json")]


def test_empty_oracle_means_an_empty_box_not_the_model(cli_files, tmp_path, monkeypatch):
    def no_model(*a, **k):
        raise AssertionError("--oracle '' must not set up the paid model")

    monkeypatch.setattr(gemini, "GeminiPerceiver", no_model)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    assert cli.main(cli_files + ["--oracle", ""]) == 0
    rec = json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))
    assert rec["outcome"]["decision"] == "STOP_AND_FIX"  # the ordered cap isn't there


def test_cli_output_switches_to_utf8(monkeypatch):
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")  # like output redirected to a file on Windows
    monkeypatch.setattr(sys, "stdout", out)
    cli.utf8_output()
    print("honey jar labelled 'शहद'")
    out.flush()
    assert "शहद" in out.buffer.getvalue().decode("utf-8")
