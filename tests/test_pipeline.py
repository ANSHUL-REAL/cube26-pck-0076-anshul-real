import json

import numpy as np
import pytest
from conftest import jpeg_bytes, make_order

from pack_manager.evidence import apply_override, compute_hash, verify
from pack_manager.models import Decision, EvidenceRecord, RecordStatus
from pack_manager.pipeline import Photo, QualityRejected, prepare_photos, verify_box
from pack_manager.quality import prepare_photo
from pack_manager.vision.base import PerceptionError
from pack_manager.vision.oracle import OraclePerceiver


class BrokenPerceiver:
    def perceive(self, *args, **kwargs):
        raise PerceptionError("timed out")


def test_quality_gate_passes_a_sharp_photo(sharp_photo, settings):
    assert prepare_photo(sharp_photo, settings).quality.gate == "PASS"


def test_quality_gate_rejects_dark_and_tiny_and_blurry(settings):
    dark = jpeg_bytes(np.full((1200, 1600, 3), 8))
    tiny = jpeg_bytes(np.random.default_rng(1).integers(0, 255, (200, 300, 3)))
    flat = jpeg_bytes(np.full((1200, 1600, 3), 128))  # no edges at all: reads as blurry
    assert any("dark" in r for r in prepare_photo(dark, settings).quality.reasons)
    assert any("small" in r for r in prepare_photo(tiny, settings).quality.reasons)
    assert any("blurry" in r for r in prepare_photo(flat, settings).quality.reasons)


def test_rejected_photo_needs_force(catalogue, settings):
    prepared = prepare_photos([Photo(jpeg_bytes(np.full((1200, 1600, 3), 8)))], settings)
    order = make_order(("CAP-BLU", 1))
    with pytest.raises(QualityRejected):
        verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings, operator_label="t")
    record = verify_box(order, prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}), settings,
                        operator_label="t", force_quality=True)
    assert record.outcome.decision == Decision.UNCERTAIN


def test_fail_open_keeps_photos_and_marks_pending(sharp_photo, catalogue, settings):
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(make_order(("CAP-BLU", 1)), prepared, catalogue, BrokenPerceiver(), settings,
                        operator_label="op_a")
    assert record.status == RecordStatus.PENDING
    assert record.outcome.decision == Decision.PENDING
    assert record.images[0].sha256 == prepared[0].sha256
    assert verify(record)


def test_record_follows_contract_and_hash_survives_round_trip(sharp_photo, catalogue, settings):
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(make_order(("CAP-BLU", 1)), prepared, catalogue, OraclePerceiver({"CAP-BLU": 1}),
                        settings, operator_label="op_a")
    data = json.loads(record.model_dump_json())
    for field in ["record_id", "schema_version", "organization_id", "client_id", "agent", "subject",
                  "captured_at", "operator_label", "images", "checks", "outcome", "overrides",
                  "status", "content_hash"]:
        assert field in data
    for check in data["checks"]:
        assert {"check_key", "verdict", "confidence", "detail", "model_version", "latency_ms"} <= set(check)
    reloaded = EvidenceRecord.model_validate(data)
    assert verify(reloaded)
    assert record.outcome.decision == Decision.SEAL


def test_any_edit_breaks_the_hash(sharp_photo, catalogue, settings):
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(make_order(("CAP-BLU", 1)), prepared, catalogue, OraclePerceiver({"CAP-RED": 1}),
                        settings, operator_label="op_a")
    tampered = record.model_copy(update={"outcome": record.outcome.model_copy(update={"decision": Decision.SEAL})})
    assert not verify(tampered)


def test_override_keeps_the_original_decision(sharp_photo, catalogue, settings):
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(make_order(("LAMP", 1)), prepared, catalogue, OraclePerceiver({"LAMP": 1, "CABLE": 1}),
                        settings, operator_label="op_a")
    assert record.outcome.decision == Decision.UNCERTAIN
    assert record.status == RecordStatus.PENDING_REVIEW
    after = apply_override(record, Decision.SEAL, "item_is_insert_or_packaging", "op_b", note="cable was in lamp box")
    assert after.status == RecordStatus.OVERRIDDEN
    assert after.outcome.decision == Decision.SEAL
    assert after.outcome.decided_by == "operator:op_b"
    ov = after.overrides[0]
    assert ov.original_decision == Decision.UNCERTAIN and ov.prior_content_hash == record.content_hash
    assert after.checks == record.checks
    assert verify(after) and after.content_hash == compute_hash(after) != record.content_hash
