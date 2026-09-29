"""The eight test scenarios from the problem statement, plus the tricky cases, against the rules."""

from conftest import good_photo, make_order, obj, perception

from pack_manager.decision import decide
from pack_manager.models import Decision, QualityReport, SkuCount, Verdict


def run(order, perc, catalogue, settings, quality=None):
    return decide(order, catalogue, perc, quality or [good_photo()], settings)


def verdicts(result):
    return {c.check_key: c.verdict for c in result.checks}


def test_correct_order_seals(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 2), ("CAP-BLU", 1))
    p = perception([obj(1, "TSHIRT-BLK"), obj(2, "TSHIRT-BLK"), obj(3, "CAP-BLU")])
    r = run(order, p, catalogue, settings)
    assert r.decision == Decision.SEAL
    assert all(v == Verdict.PASS for v in verdicts(r).values())
    assert r.fix_instructions == []


def test_portal_example_blue_cap_vs_red_cap(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 2), ("CAP-BLU", 1))
    p = perception([obj(1, "TSHIRT-BLK"), obj(2, "TSHIRT-BLK"), obj(3, "CAP-RED")])
    r = run(order, p, catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    v = verdicts(r)
    assert v["wrong_item"] == Verdict.FAIL
    assert v["extra_item"] == Verdict.PASS  # the red cap is a substitution, not an extra
    wrong = [c for c in r.checks if c.check_key == "wrong_item"][0]
    assert "Expected Blue Cap, found Red Cap (#3)" in wrong.detail
    assert r.reasons[0] == wrong.detail  # the substitution is the headline, not "blue cap missing"
    assert r.fix_instructions == ["Replace Red Cap (#3) with Blue Cap."]


def test_missing_item(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 1), ("CAP-BLU", 1))
    r = run(order, perception([obj(1, "TSHIRT-BLK")]), catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    assert verdicts(r)["line_present:CAP-BLU"] == Verdict.FAIL
    assert "Add 1 × Blue Cap." in r.fix_instructions


def test_extra_item(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    r = run(order, perception([obj(1, "CAP-BLU"), obj(2, "CABLE")]), catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    assert verdicts(r)["extra_item"] == Verdict.FAIL
    assert r.observations["extra"][0]["sku"] == "CABLE"


def test_unknown_extra_product(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    p = perception([obj(1, "CAP-BLU"), obj(2, None, desc="a green toy car")])
    r = run(order, p, catalogue, settings)
    assert verdicts(r)["extra_item"] == Verdict.FAIL
    assert "a green toy car" in r.fix_instructions[0]


def test_short_quantity(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 3))
    r = run(order, perception([obj(1, "TSHIRT-BLK"), obj(2, "TSHIRT-BLK")]), catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    assert verdicts(r)["line_quantity:TSHIRT-BLK"] == Verdict.FAIL
    assert verdicts(r)["line_present:TSHIRT-BLK"] == Verdict.PASS
    assert "Add 1 × Black T-Shirt." in r.fix_instructions


def test_over_quantity(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 1))
    r = run(order, perception([obj(1, "TSHIRT-BLK"), obj(2, "TSHIRT-BLK")]), catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    assert "Remove 1 × Black T-Shirt." in r.fix_instructions


def test_many_identical_items_counted(catalogue, settings):
    order = make_order(("MUG-SET2", 4))
    r = run(order, perception([obj(i, "MUG-SET2") for i in range(1, 5)]), catalogue, settings)
    assert r.decision == Decision.SEAL


def test_stacked_items_uncertain_not_guessed(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 3))
    p = perception(
        [obj(1, "TSHIRT-BLK"), obj(2, "TSHIRT-BLK")],
        counts=[SkuCount(sku="TSHIRT-BLK", count=2, count_certain=False)],
        hidden=True,
    )
    r = run(order, p, catalogue, settings)
    assert r.decision == Decision.UNCERTAIN
    assert verdicts(r)["line_quantity:TSHIRT-BLK"] == Verdict.UNCERTAIN
    assert any("Count Black T-Shirt by hand" in h for h in r.fix_instructions)


def test_hidden_items_cannot_fail_missing_but_can_fail_extra(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    # Something may be hidden, but a confident extra product is still a certain problem.
    p = perception([obj(1, "CAP-BLU"), obj(2, "CABLE")], hidden=True)
    r = run(order, p, catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    # And with nothing wrong visible, hidden space means UNCERTAIN, not SEAL or FAIL.
    r2 = run(make_order(("CAP-BLU", 1), ("TSHIRT-BLK", 1)), perception([obj(1, "CAP-BLU")], hidden=True),
             catalogue, settings)
    assert r2.decision == Decision.UNCERTAIN
    assert verdicts(r2)["line_present:TSHIRT-BLK"] == Verdict.UNCERTAIN


def test_visually_similar_low_confidence_is_uncertain(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    p = perception([obj(1, "CAP-RED", conf=0.55, alts=["CAP-BLU"])])
    r = run(order, p, catalogue, settings)
    assert r.decision == Decision.UNCERTAIN
    v = verdicts(r)
    assert v["line_present:CAP-BLU"] == Verdict.UNCERTAIN
    assert v["wrong_item"] == Verdict.UNCERTAIN


def test_visually_similar_confident_correct_seals(catalogue, settings):
    order = make_order(("TSHIRT-NVY", 1))
    r = run(order, perception([obj(1, "TSHIRT-NVY", conf=0.9)]), catalogue, settings)
    assert r.decision == Decision.SEAL


def test_packing_slip_and_filler_are_not_extra(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    p = perception([
        obj(1, "CAP-BLU"),
        obj(2, cls="NON_PRODUCT", desc="packing slip"),
        obj(3, cls="NON_PRODUCT", desc="air pillows"),
    ])
    r = run(order, p, catalogue, settings)
    assert r.decision == Decision.SEAL
    assert len(r.observations["non_product_items"]) == 2


def test_loose_cable_next_to_lamp_is_ambiguous(catalogue, settings):
    order = make_order(("LAMP", 1))
    r = run(order, perception([obj(1, "LAMP"), obj(2, "CABLE")]), catalogue, settings)
    assert r.decision == Decision.UNCERTAIN
    assert verdicts(r)["extra_item"] == Verdict.UNCERTAIN


def test_empty_box(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    r = run(order, perception([]), catalogue, settings)
    assert r.decision == Decision.STOP_AND_FIX
    assert verdicts(r)["line_present:CAP-BLU"] == Verdict.FAIL


def test_forced_bad_photo_never_seals(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    bad = QualityReport(gate="FAIL", reasons=["Photo looks blurry."], width=1600, height=1200,
                        blur_var=10, mean_luma=120, clipped_pct=0, dark_pct=0)
    r = run(order, perception([obj(1, "CAP-BLU")]), catalogue, settings, quality=[bad])
    assert r.decision == Decision.UNCERTAIN
    assert verdicts(r)["image_quality"] == Verdict.UNCERTAIN


def test_model_count_disagreeing_with_objects_is_uncertain(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 2))
    p = perception([obj(1, "TSHIRT-BLK")], counts=[SkuCount(sku="TSHIRT-BLK", count=2, count_certain=True)])
    r = run(order, p, catalogue, settings)
    assert verdicts(r)["line_quantity:TSHIRT-BLK"] == Verdict.UNCERTAIN


def test_checks_from_the_model_share_model_version_and_latency(catalogue, settings):
    order = make_order(("CAP-BLU", 1))
    r = run(order, perception([obj(1, "CAP-BLU")]), catalogue, settings)
    model_checks = [c for c in r.checks if c.check_key != "image_quality"]
    assert {c.model_version for c in model_checks} == {"test-model"}
    assert {c.latency_ms for c in model_checks} == {1234}


# ---- uncertainty summary: known / unknown / missing evidence / next action


def test_sealed_box_has_no_uncertainty_summary(catalogue, settings):
    r = run(make_order(("CAP-BLU", 1)), perception([obj(1, "CAP-BLU")]), catalogue, settings)
    assert r.observations["uncertainty"] is None


def test_stacked_items_summary_says_what_would_settle_it(catalogue, settings):
    order = make_order(("TSHIRT-BLK", 3))
    p = perception([obj(1, "TSHIRT-BLK"), obj(2, "TSHIRT-BLK")], hidden=True, vis_conf=0.5,
                   counts=[SkuCount(sku="TSHIRT-BLK", count=2, count_certain=False)])
    r = run(order, p, catalogue, settings)
    u = r.observations["uncertainty"]
    assert r.decision == Decision.UNCERTAIN
    assert any("Black T-Shirt" in x for x in u["unknown"])
    assert "A count of Black T-Shirt with every unit visible." in u["missing_evidence"]
    assert any("stacked or covered" in x for x in u["missing_evidence"])
    assert u["next_action"].startswith("Don't seal yet.")
    assert all("Black T-Shirt: found" not in x for x in u["unknown"])  # facts go to "known"


def test_loose_cable_summary_asks_if_it_is_inside_the_lamp_box(catalogue, settings):
    p = perception([obj(1, "LAMP"), obj(2, "CABLE")])
    r = run(make_order(("LAMP", 1)), p, catalogue, settings)
    u = r.observations["uncertainty"]
    assert "Whether #2 is loose or packed inside the Desk Lamp box." in u["missing_evidence"]


def test_bad_photo_only_summary_says_retake(catalogue, settings):
    blurry = QualityReport(gate="FAIL", reasons=["Photo looks blurry."], width=1600, height=1200,
                           blur_var=10, mean_luma=120, clipped_pct=0, dark_pct=0)
    r = run(make_order(("CAP-BLU", 1)), perception([obj(1, "CAP-BLU")]), catalogue, settings, quality=[blurry])
    u = r.observations["uncertainty"]
    assert r.decision == Decision.UNCERTAIN
    assert u["next_action"].startswith("Retake the photo")
    assert u["missing_evidence"] == ["A sharp, well-lit photo. Photo looks blurry."]


def test_photo_used_for_another_order_cannot_seal(catalogue, settings):
    order = make_order(("CAP-BLU", 1), order_id="ORD-9")
    earlier = [{"sha256": "x", "record_id": "PCK-OLD", "order_id": "ORD-1"}]
    r = decide(order, catalogue, perception([obj(1, "CAP-BLU")]), [good_photo()], settings, earlier_uses=earlier)
    assert r.decision == Decision.UNCERTAIN
    assert verdicts(r)["photo_reuse"] == Verdict.UNCERTAIN
    assert r.reasons[0].startswith("This exact photo was already used for another order (ORD-1)")


def test_reuse_not_checked_adds_no_check(catalogue, settings):
    r = run(make_order(("CAP-BLU", 1)), perception([obj(1, "CAP-BLU")]), catalogue, settings)
    assert "photo_reuse" not in verdicts(r)


def test_model_descriptions_read_well_mid_sentence():
    from pack_manager.decision import _short

    assert _short("A white rectangular box.") == "a white rectangular box"
    assert _short("  An   open  bag ") == "an open bag"
    assert _short("Apple charger") == "Apple charger"
    long = "A white rectangular box or carton with 'CERAMIC MUG x2' printed on its visible surface."
    out = _short(long)
    assert out.startswith("a white rectangular box") and out.endswith("…") and len(out) <= 61
