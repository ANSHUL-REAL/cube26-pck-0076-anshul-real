"""The eval packing plan: right mix, packable with what's at home, and truths that match the kind."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from common import Box  # noqa: E402
from plan_boxes import DEV_MIX, TEST_MIX, make_plan, write_checklist, write_manifest  # noqa: E402

from pack_manager.models import Catalogue, CatalogueItem  # noqa: E402


def home_catalogue():
    items = [
        CatalogueItem(sku="CAP-BLUE", title="Cap", attributes={"colour": "blue"}, confusable_with=["CAP-RED"]),
        CatalogueItem(sku="CAP-RED", title="Cap", attributes={"colour": "red"}, confusable_with=["CAP-BLUE"]),
        CatalogueItem(sku="BOOK-1", title="Novel vol 1", confusable_with=["BOOK-2"]),
        CatalogueItem(sku="BOOK-2", title="Novel vol 2", confusable_with=["BOOK-1"]),
        CatalogueItem(sku="SOAP", title="Soap bar"),
        CatalogueItem(sku="MUG-SET2", title="Mug set of 2"),
        CatalogueItem(sku="CABLE", title="USB cable"),
        CatalogueItem(sku="SOCKS", title="Socks"),
    ]
    return Catalogue(organization_id="org_demo_alpha", items=items)


ON_HAND = {"SOAP": 4, "SOCKS": 3, "CABLE": 2, "BOOK-1": 2}


def test_plan_has_the_right_mix_and_can_be_packed():
    boxes, warnings = make_plan(home_catalogue(), ON_HAND)
    assert warnings == []
    for split, mix in (("dev", DEV_MIX), ("test", TEST_MIX)):
        got = Counter(b.scenario for b in boxes if b.split == split)
        assert got == Counter(dict(mix)), split
    assert len({b.box_id for b in boxes}) == 70
    assert [b.box_id for b in boxes][:2] == ["D01", "D02"] and boxes[20].box_id == "T01"
    have = {**{i.sku: 1 for i in home_catalogue().items}, **ON_HAND}
    for b in boxes:
        assert all(n <= have[s] for s, n in b.actual.items()), b.box_id
        truth = Box(b.box_id, b.split, b.scenario, *[b.row()[k] for k in
                    ("order_lines", "actual_contents", "conditions", "notes")]).decision_truth
        if b.scenario in ("correct", "similar_products"):
            assert truth == "SEAL", b.box_id
        if b.scenario in ("missing", "wrong_item", "extra", "wrong_qty"):
            assert truth == "STOP_AND_FIX", b.box_id
    # both kinds of truth are well represented in the held-out set
    test_truths = Counter(Box(**{**{k: "" for k in Box.__dataclass_fields__}, **{
        "order_lines": b.row()["order_lines"], "actual_contents": b.row()["actual_contents"]}}).decision_truth
        for b in boxes if b.split == "test")
    assert test_truths == {"SEAL": 24, "STOP_AND_FIX": 26}  # as EVAL.md states


def test_kinds_are_mixed_and_plan_is_reproducible():
    a, _ = make_plan(home_catalogue(), ON_HAND, seed=7)
    b, _ = make_plan(home_catalogue(), ON_HAND, seed=7)
    assert [x.row() for x in a] == [x.row() for x in b]
    test = [x.scenario for x in a if x.split == "test"]
    assert test[:12] != ["correct"] * 12  # the box number doesn't give the answer away


def test_falls_back_when_there_is_only_one_of_everything():
    one_each = Catalogue(organization_id="x", items=[CatalogueItem(sku=f"P{i}", title=f"Item {i}") for i in range(6)])
    boxes, warnings = make_plan(one_each, {})
    kinds = Counter(b.scenario for b in boxes)
    assert kinds["wrong_qty"] == kinds["identical_multiples"] == kinds["similar_products"] == 0
    assert len(warnings) == 6  # three kinds, in both splits


def test_files_are_written(tmp_path):
    boxes, _ = make_plan(home_catalogue(), ON_HAND)
    write_manifest(boxes, tmp_path / "manifest.csv")
    write_checklist(boxes, lambda s: s, tmp_path / "plan.html")
    assert (tmp_path / "manifest.csv").read_text(encoding="utf-8").count("\n") == 71
    page = (tmp_path / "plan.html").read_text(encoding="utf-8")
    assert "This is the answer key." in page and page.count('class="box ') == 70
    for card in page.split('class="box ')[1:]:  # a dim-light box never also says "Lamp light"
        assert not ("lamp off" in card and "Lamp light" in card)
