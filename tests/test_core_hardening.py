"""Edge cases found in review: bad inputs must give a clear error or a hand check, never a crash
or a confident wrong answer, and the evidence must stay checkable."""

import io

import pytest
from conftest import make_order
from PIL import Image

from pack_manager.catalogue import reference_images
from pack_manager.evidence import apply_override, verify, verify_history
from pack_manager.models import Catalogue, CatalogueItem, Decision, parse_lines
from pack_manager.orders import parse_orders_csv
from pack_manager.pipeline import Photo, prepare_photos, verify_box
from pack_manager.quality import ImageDecodeError, prepare_photo
from pack_manager.vision.oracle import OraclePerceiver


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 110, 100)).save(buf, "PNG")
    return buf.getvalue()


def test_parse_lines_rejects_commas_and_missing_skus():
    assert [(x.sku, x.qty) for x in parse_lines("CAP-BLU:1; CAP-RED:2")] == [("CAP-BLU", 1), ("CAP-RED", 2)]
    for bad in ["CAP-BLU:1,CAP-RED:2", ":2", "CAP-BLU", "CAP-BLU:0"]:
        with pytest.raises(ValueError):
            parse_lines(bad)


def test_order_import_reports_bad_rows_instead_of_crashing():
    text = ("order_id,order_lines\n"
            "ORD-1,CAP-BLU:1,\n"            # trailing comma: an extra column
            "#1001,CAP-BLU:1\n"             # Shopify-style name: '#' dropped
            "A/B,CAP-BLU:1\n"               # unsafe in a page address
            "import,CAP-BLU:1\n"            # the name of a page
            "ORD-2,CAP-BLU:1,CAP-RED:2\n")  # commas between lines
    result = parse_orders_csv(text, "org_test", Catalogue(items=[CatalogueItem(sku="CAP-BLU", title="Blue Cap")]))
    assert [o.order_id for o in result.orders] == ["1001"]
    assert len(result.problems) == 4


def test_override_chain_can_be_rebuilt_and_checked(sharp_photo, settings):
    catalogue = Catalogue(items=[CatalogueItem(sku="CAP-BLU", title="Blue Cap")])
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    record = verify_box(make_order(("CAP-BLU", 1)), prepared, catalogue, OraclePerceiver({}), settings,
                        operator_label="op")
    once = apply_override(record, Decision.SEAL, "box_fixed", "op_a")
    twice = apply_override(once, Decision.STOP_AND_FIX, "other", "op_b", note="second look")
    assert verify_history(record) is True and verify_history(twice) is True

    edited = twice.model_copy(update={"checks": twice.checks[:-1]})  # someone drops a check
    assert verify_history(edited) is False
    with pytest.raises(ValueError, match="content hash"):
        apply_override(edited, Decision.SEAL, "other", "op_c")  # a new hash must not hide the edit

    # An earlier version edited: the latest record still verifies, the chain does not.
    forged = twice.overrides[-1].model_copy(update={"prior_status": record.status})
    tampered = twice.model_copy(update={"overrides": [twice.overrides[0], forged]})
    tampered = tampered.model_copy(update={"content_hash": None})
    from pack_manager.evidence import seal
    tampered = seal(tampered)
    assert verify(tampered) and verify_history(tampered) is False


def test_no_photos_or_no_lines_is_an_error_not_a_seal(sharp_photo, settings):
    catalogue = Catalogue(items=[CatalogueItem(sku="CAP-BLU", title="Blue Cap")])
    with pytest.raises(ValueError, match="photo"):
        verify_box(make_order(("CAP-BLU", 1)), [], catalogue, OraclePerceiver({}), settings, operator_label="op")
    empty = make_order(("CAP-BLU", 1)).model_copy(update={"lines": []})
    prepared = prepare_photos([Photo(sharp_photo)], settings)
    with pytest.raises(ValueError, match="no lines"):
        verify_box(empty, prepared, catalogue, OraclePerceiver({}), settings, operator_label="op")


@pytest.mark.parametrize("data", [_png(20000, 20000), _png(7000, 6000), b"\x89PNG\r\n\x1a\nnot an image", b""],
                         ids=["bomb-header", "42-megapixels", "corrupt", "empty"])
def test_oversized_or_broken_images_are_a_clear_error(data, settings):
    with pytest.raises(ImageDecodeError):
        prepare_photo(data, settings)


def test_a_one_pixel_high_image_does_not_crash(settings):
    report = prepare_photo(_png(3000, 1), settings).quality
    assert report.gate == "FAIL"  # too small, but no crash


def test_metadata_is_stripped(settings):
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (90, 140, 60)).save(buf, "JPEG", comment=b"home address")
    assert b"home address" not in prepare_photo(buf.getvalue(), settings).jpeg


def test_unreadable_reference_photo_is_skipped(tmp_path, settings):
    (tmp_path / "good.png").write_bytes(_png(600, 600))
    (tmp_path / "bad.jpg").write_bytes(b"not a photo")
    item = CatalogueItem(sku="CAP-BLU", title="Blue Cap", reference_images=["bad.jpg", "good.png"])
    assert len(reference_images(item, tmp_path, settings)) == 1
