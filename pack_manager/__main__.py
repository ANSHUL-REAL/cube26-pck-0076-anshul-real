"""Command line: python -m pack_manager <command>

  verify         check one box: order JSON + photo(s) -> evidence record JSON
  check-record   check a downloaded evidence record (and its photos) against its hashes
  replay-sample  run the organisers' pack_sample.csv through the decision engine
  models         list the Gemini models your API key can use
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .catalogue import load_catalogue
from .config import get_settings
from .models import Decision, Order, parse_lines
from .pipeline import Photo, QualityRejected, prepare_photos, verify_box


def cmd_verify(args) -> int:
    settings = get_settings()
    catalogue = load_catalogue(args.catalogue)
    order = Order.model_validate(json.loads(Path(args.order).read_text(encoding="utf-8")))
    prepared = prepare_photos([Photo(Path(p).read_bytes()) for p in args.photo], settings)

    if args.oracle is not None:  # --oracle "" means an empty box, not "use the model"
        from .vision.oracle import OraclePerceiver

        observed = Order(order_id="obs", organization_id="obs", lines=parse_lines(args.oracle)).expected()
        perceiver = OraclePerceiver(observed)
    else:
        from .vision.gemini import GeminiPerceiver

        perceiver = GeminiPerceiver(settings)

    try:
        record = verify_box(
            order, prepared, catalogue, perceiver, settings,
            operator_label=args.operator, catalogue_root=Path(args.catalogue), force_quality=args.force,
        )
    except QualityRejected as exc:
        for i, r in enumerate(exc.reports, 1):
            if r.gate == "FAIL":
                print(f"Photo {i} rejected: {' '.join(r.reasons)}", file=sys.stderr)
        print("Retake the photo, or pass --force to continue anyway.", file=sys.stderr)
        return 2

    out = record.model_dump_json(indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    else:
        print(out)
    o = record.outcome
    print(f"\n{o.decision.value}  ({record.record_id})", file=sys.stderr)
    for line in o.fix_instructions:
        print(f"  - {line}", file=sys.stderr)
    return 0


def cmd_check_record(args) -> int:
    """For whoever holds a downloaded record, e.g. to answer a buyer's claim: does it still match
    its content hash, and are these the photos it was made from? Exit 0 if everything matches."""
    from .evidence import verify, verify_history
    from .models import EvidenceRecord

    try:
        record = EvidenceRecord.model_validate_json(Path(args.record).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Can't read {args.record} as an evidence record: {exc}", file=sys.stderr)
        return 2

    good = verify(record)
    print(f"{record.record_id} · order {record.subject.get('order_id', '?')} · {record.outcome.decision.value}"
          f" · checked {record.captured_at:%Y-%m-%d %H:%M} UTC")
    print("OK   the record matches its content hash" if good else
          "BAD  the record does not match its content hash: its contents are not what was hashed")
    if good and record.overrides:
        history = verify_history(record)
        n = len(record.overrides)
        if history is True:
            print(f"OK   the agent's result and {n} later hand decision{'s' if n > 1 else ''} all match their hashes")
        elif history is None:
            print("?    earlier versions can't be rebuilt: a hand decision was saved before overrides kept them")
        else:
            good = False
            print("BAD  an earlier version does not match its hash")

    for path in args.photo or []:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        found = [f"photo {i} ({kind})" for i, img in enumerate(record.images, 1)
                 for kind, h in (("the stored copy", img.sha256), ("the original upload", img.original_sha256))
                 if h == digest]
        good = good and bool(found)
        print(f"OK   {path} is {found[0]}" if found else f"BAD  {path} is not one of this record's photos")
    return 0 if good else 1


def cmd_replay(args) -> int:
    from .sample import replay

    rows = replay(args.csv, load_catalogue(args.catalogue), get_settings())
    bad = [r for r in rows if r.truth == "stop_and_fix"]
    caught = [r for r in bad if r.agent_decision == Decision.STOP_AND_FIX]
    operator_caught = [r for r in bad if r.operator_verdict == "stop_and_fix"]
    false_stops = [r for r in rows if r.truth == "seal" and r.agent_decision != Decision.SEAL]
    print(f"{'record':10} {'ordered':38} {'in box':52} {'operator':13} agent")
    for r in rows:
        mark = "  <- operator missed" if r in bad and r.operator_verdict == "seal" else ""
        print(f"{r.record_id:10} {r.ordered:38} {r.observed:52} {r.operator_verdict:13} {r.agent_decision.value}{mark}")
        for fix in r.fix_instructions:
            print(f"{'':12}fix: {fix}")
    print(f"\n{len(rows)} boxes, {len(bad)} with wrong contents.")
    print(f"Rules caught {len(caught)}/{len(bad)}; the operator caught {len(operator_caught)}/{len(bad)}.")
    print(f"Correct boxes stopped by the rules: {len(false_stops)}.")
    return 0


def cmd_models(_args) -> int:
    from .vision.gemini import list_models

    for name in list_models(get_settings()):
        print(name)
    return 0


def utf8_output() -> None:
    """Windows consoles and redirected output default to cp1252, which can't print model text
    such as Hindi labels. Switch to UTF-8 where the stream allows it."""
    for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "replace")):
        try:
            stream.reconfigure(encoding="utf-8", errors=errors)
        except (AttributeError, ValueError, OSError):  # not a reconfigurable text stream
            pass


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    parser = argparse.ArgumentParser(prog="pack_manager", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    v = sub.add_parser("verify", help="check one box")
    v.add_argument("--catalogue", required=True, help="folder containing catalogue.json")
    v.add_argument("--order", required=True, help="order JSON file")
    v.add_argument("--photo", required=True, action="append", help="photo of the open box (repeatable)")
    v.add_argument("--operator", default="cli")
    v.add_argument("--force", action="store_true", help="continue even if a photo fails the quality gate")
    v.add_argument("--oracle", help="skip the model; treat these contents as seen, e.g. 'SKU-A:2;SKU-B:1'")
    v.add_argument("--out", help="write the evidence record here instead of stdout")
    v.set_defaults(func=cmd_verify)

    c = sub.add_parser("check-record", help="check a downloaded evidence record against its hashes")
    c.add_argument("record", help="the record's JSON file (Download record on its page)")
    c.add_argument("--photo", action="append", help="a photo to match against the record's photos (repeatable)")
    c.set_defaults(func=cmd_check_record)

    r = sub.add_parser("replay-sample", help="replay the organisers' sample CSV")
    r.add_argument("--csv", default="data/pack_sample.csv")
    r.add_argument("--catalogue", default="catalogue/sample")
    r.set_defaults(func=cmd_replay)

    m = sub.add_parser("models", help="list available Gemini models")
    m.set_defaults(func=cmd_models)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
