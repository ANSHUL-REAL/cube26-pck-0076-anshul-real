from conftest import ROOT, make_order

from pack_manager.catalogue import load_catalogue, select_candidates
from pack_manager.models import Decision
from pack_manager.sample import replay
from pack_manager.vision.prompt import VisionResponse, build_parts, normalise


def test_sample_replay_catches_every_wrong_box(settings):
    rows = replay(ROOT / "data" / "pack_sample.csv", load_catalogue(ROOT / "catalogue" / "sample"), settings)
    assert len(rows) == 29
    bad = [r for r in rows if r.truth == "stop_and_fix"]
    assert {r.record_id for r in bad} == {"PCK-0027", "PCK-0034", "PCK-0044", "PCK-0078"}
    assert all(r.agent_decision == Decision.STOP_AND_FIX for r in bad)
    assert all(r.agent_decision == Decision.SEAL for r in rows if r.truth == "seal")
    # The sample's human operator sealed two of the four wrong boxes.
    assert {r.record_id for r in bad if r.operator_verdict == "seal"} == {"PCK-0034", "PCK-0044"}


def test_candidates_include_lookalikes_and_hide_the_order(catalogue, settings):
    order = make_order(("CAP-BLU", 1), ("LAMP", 1))
    skus = [c.sku for c in select_candidates(order, catalogue, settings)]
    assert {"CAP-BLU", "LAMP", "CAP-RED", "CABLE"} <= set(skus)
    assert len(skus) <= settings.max_candidates
    assert skus == [c.sku for c in select_candidates(order, catalogue, settings)]  # deterministic
    text = " ".join(p for p in build_parts([b"x"], [(c, []) for c in select_candidates(order, catalogue, settings)], ["packing slip"]) if isinstance(p, str))
    assert "qty" not in text.lower() and "ordered" not in text.lower()


def test_normalise_rejects_invented_skus_and_bad_boxes():
    raw = VisionResponse.model_validate({
        "objects": [
            {"object_id": "a", "photo": 3, "box_2d": [100, 100, 50, 900], "description": "cap",
             "classification": "CANDIDATE", "sku": "CAP-GREEN", "confidence": 1.4,
             "alternative_skus": ["CAP-BLU", "NOPE"], "deciding_feature": "", "partially_hidden": False},
            {"object_id": "b", "photo": 1, "box_2d": [10, 10, 500, 500], "description": "cap",
             "classification": "CANDIDATE", "sku": "CAP-BLU", "confidence": 0.9,
             "alternative_skus": [], "deciding_feature": "blue", "partially_hidden": False},
        ],
        "counts": [{"sku": "CAP-BLU", "count": 1, "count_certain": True, "reason": ""},
                   {"sku": "CAP-GREEN", "count": 1, "count_certain": True, "reason": ""}],
        "scene": {"box_interior_fully_visible": True, "items_may_be_hidden": False,
                  "visibility_confidence": 0.9, "notes": ""},
        "image_issues": [],
    })
    objects, counts, scene, _ = normalise(raw, ["CAP-BLU", "CAP-RED"], n_photos=1)
    assert objects[0].classification == "UNKNOWN_PRODUCT" and objects[0].sku is None
    assert objects[0].confidence == 1.0 and objects[0].photo == 1 and objects[0].box_2d is None
    assert objects[0].alternative_skus == ["CAP-BLU"]
    assert objects[1].sku == "CAP-BLU" and objects[1].box_2d == [10, 10, 500, 500]
    assert [c.sku for c in counts] == ["CAP-BLU"]


def test_normalise_repairs_small_slips_and_keeps_self_contradicting_objects():
    import math as _math

    from pack_manager.vision.prompt import VisionResponse, normalise

    resp = VisionResponse.model_validate({
        "objects": [
            # float box, missing deciding_feature, lower-case sku
            {"object_id": "o1", "photo": 1, "box_2d": [10.4, 20.6, 500.2, 600.9], "description": "cap",
             "classification": "CANDIDATE", "sku": " cap-blu ", "confidence": 0.9, "alternative_skus": [],
             "partially_hidden": False},
            # called packaging but also named a candidate
            {"object_id": "o2", "photo": 1, "box_2d": [1, 1, 50, 50], "description": "coiled cable",
             "classification": "NON_PRODUCT", "sku": "CABLE", "confidence": 0.9, "alternative_skus": [],
             "deciding_feature": "", "partially_hidden": False},
            {"object_id": "o3", "photo": 1, "box_2d": [1, 1, 50, 50], "description": "?",
             "classification": "UNKNOWN_PRODUCT", "sku": "", "confidence": _math.nan, "alternative_skus": [],
             "deciding_feature": "", "partially_hidden": False},
        ],
        "counts": [{"sku": "CAP-BLU ", "count": 1, "count_certain": True, "reason": ""}],
        "scene": {"box_interior_fully_visible": True, "items_may_be_hidden": False,
                  "visibility_confidence": 0.9, "notes": ""},
        "image_issues": [],
    })
    objects, counts, _, _ = normalise(resp, ["CAP-BLU", "CABLE"], n_photos=1)
    assert objects[0].sku == "CAP-BLU" and objects[0].box_2d == [10, 21, 500, 601]
    assert (objects[1].classification, objects[1].sku, objects[1].alternative_skus) == ("UNKNOWN_PRODUCT", None, ["CABLE"])
    assert objects[1].confidence <= 0.5
    assert objects[2].confidence == 0.0  # NaN is not "certain"
    assert [c.sku for c in counts] == ["CAP-BLU"]
