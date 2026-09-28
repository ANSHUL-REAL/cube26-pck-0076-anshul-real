import io
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pack_manager.config import Settings  # noqa: E402
from pack_manager.models import (  # noqa: E402
    Catalogue,
    CatalogueItem,
    DetectedObject,
    Order,
    OrderLine,
    Perception,
    QualityReport,
    Scene,
    SkuCount,
)


@pytest.fixture
def settings():
    return Settings(_env_file=None, gemini_api_key=None, cache_dir=str(ROOT / ".cache" / "test"))


@pytest.fixture
def catalogue():
    return Catalogue(
        organization_id="org_test",
        items=[
            CatalogueItem(sku="TSHIRT-BLK", title="Black T-Shirt", confusable_with=["TSHIRT-NVY"]),
            CatalogueItem(sku="TSHIRT-NVY", title="Navy T-Shirt", confusable_with=["TSHIRT-BLK"]),
            CatalogueItem(sku="CAP-BLU", title="Blue Cap", confusable_with=["CAP-RED"],
                          distinguishing_features="blue fabric"),
            CatalogueItem(sku="CAP-RED", title="Red Cap", confusable_with=["CAP-BLU"]),
            CatalogueItem(sku="LAMP", title="Desk Lamp", component_lookalikes=["CABLE"]),
            CatalogueItem(sku="CABLE", title="USB-C Cable"),
            CatalogueItem(sku="MUG-SET2", title="Mug set of 2", sellable_unit="one box with 2 mugs"),
        ],
    )


def make_order(*lines, order_id="ORD-1"):
    return Order(order_id=order_id, organization_id="org_test",
                 lines=[OrderLine(sku=s, qty=q) for s, q in lines])


def obj(i, sku=None, conf=0.95, cls=None, alts=None, desc=""):
    return DetectedObject(
        object_id=f"o{i}",
        classification=cls or ("CANDIDATE" if sku else "UNKNOWN_PRODUCT"),
        sku=sku, confidence=conf, alternative_skus=alts or [], description=desc,
    )


def perception(objects, counts=None, visible=True, hidden=False, vis_conf=0.95):
    if counts is None:
        tally = {}
        for o in objects:
            if o.sku and o.classification == "CANDIDATE":
                tally[o.sku] = tally.get(o.sku, 0) + 1
        counts = [SkuCount(sku=s, count=n, count_certain=True) for s, n in tally.items()]
    return Perception(
        objects=objects, counts=counts,
        scene=Scene(box_interior_fully_visible=visible, items_may_be_hidden=hidden, visibility_confidence=vis_conf),
        model_version="test-model", prompt_version="test", latency_ms=1234,
    )


def good_photo():
    return QualityReport(gate="PASS", width=1600, height=1200, blur_var=300, mean_luma=120,
                         clipped_pct=0.1, dark_pct=0.1)


def jpeg_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype("uint8")).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.fixture
def sharp_photo():
    rng = np.random.default_rng(0)
    base = np.full((1200, 1600, 3), 120, dtype=np.uint8)
    # checkerboard with texture: lots of edges -> high Laplacian variance
    yy, xx = np.mgrid[0:1200, 0:1600]
    board = (((yy // 40) + (xx // 40)) % 2 * 90).astype(np.uint8)
    base = base + board[..., None] // 2 + rng.integers(0, 20, (1200, 1600, 1), dtype=np.uint8)
    return jpeg_bytes(base)
