import json
import sys

from conftest import ROOT

from pack_manager.evidence import verify
from pack_manager.models import EvidenceRecord

sys.path.insert(0, str(ROOT / "contract"))
from build_contract import SCHEMA_PATH, schema  # noqa: E402


def test_published_schema_matches_the_code():
    published = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert published == json.loads(json.dumps(schema())), "run: python contract/build_contract.py"


def test_examples_are_valid_sealed_records():
    examples = sorted((ROOT / "contract" / "examples").glob("*.json"))
    assert {p.stem for p in examples} >= {"seal", "stop_and_fix", "uncertain", "pending", "overridden"}
    for path in examples:
        record = EvidenceRecord.model_validate_json(path.read_text(encoding="utf-8"))
        assert verify(record), f"{path.name}: content_hash does not match"


def test_override_keeps_the_agent_decision():
    record = EvidenceRecord.model_validate_json((ROOT / "contract/examples/overridden.json").read_text("utf-8"))
    uncertain = EvidenceRecord.model_validate_json((ROOT / "contract/examples/uncertain.json").read_text("utf-8"))
    assert record.overrides[0].original_decision.value == "UNCERTAIN"
    assert record.overrides[0].prior_content_hash == uncertain.content_hash
    assert record.checks == uncertain.checks
