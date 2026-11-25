"""Controlled fixtures exercise the professional-label route without seeding production."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible import expert_document_review as er


def record(root, text, case, verdict, *, authorized=True, form="production_brief"):
    source = root / "specimen.md"
    source.write_text(text, encoding="utf-8")
    return er.append_expert_label(root, source, form, verdict, reviewer="Fixture reviewer",
                                  role="Fixture production editor", case_id=case,
                                  evidence="Test-only signed review receipt", training_authorized=authorized)


def test_permission_provenance_and_failure_states(tmp_path):
    legacy = tmp_path / ".agents/bench/human_labels.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"verdict":"pass"}\n', encoding="utf-8")
    assert not er.train_expert_model(tmp_path, "production_brief")["ok"]
    with pytest.raises(ValueError, match="permission"):
        record(tmp_path, "document", "case", "pass", authorized=False)
    assert not (tmp_path / er.STORE).exists()
    row = record(tmp_path, "A sample text.", "case", "pass")
    record(tmp_path, "A sample text.", "case", "pass")
    files = list((tmp_path / er.STORE).rglob("*.json"))
    assert len(files) == 1
    assert "A sample text." not in files[0].read_text()
    record(tmp_path, "A sample text.", "case", "fail")
    result = er.train_expert_model(tmp_path, "production_brief")
    assert "Conflicting reviews" in result["reason"]
    assert "document_sha256" in row


def test_separates_cases_and_abstains_on_foreign_form(tmp_path):
    good = er.GOLDEN_SPECIMENS["production_brief"]["text"]
    bad = "TBD. No information."
    for case in ("One", "Two", "Six"):
        record(tmp_path, good + "\n" + case, case, "pass")
        record(tmp_path, bad + " " + case, case, "fail")
    result = er.train_expert_model(tmp_path, "production_brief")
    assert result["ok"] and result["held_out_case_count"] == 3
    assert result["class_recall"] == {"pass": 1, "fail": 1}
    for text, expected in [(good + "\nTen", "pass"), (bad + " Ten", "fail")]:
        advisory = er.assess_document(text, "production_brief", repo_root=tmp_path)
        assert advisory["recommendation"] == expected
        assert advisory["requires_human_review"]
        review = er.review_document(text, "production_brief", repo_root=tmp_path)
        assert review.verdict == "UNAVAILABLE" and not review.ok and not review.axis_scores
    assert er.assess_document(good, "research_note", repo_root=tmp_path)["recommendation"] == "abstain"
    assert er.assess_document("An entirely different document. " * 60, "production_brief",
                              repo_root=tmp_path)["recommendation"] == "abstain"
    # Same document cannot enter the training partition under a second assignment.
    record(tmp_path, good + "\nOne", "Different", "pass")
    assert not er.train_expert_model(tmp_path, "production_brief")["ok"]


def test_insufficient_distinct_assignments_and_corrupt_record(tmp_path):
    for idx in range(4):
        record(tmp_path, f"Proposed brief {idx}", "one assignment", "pass" if idx % 2 else "fail")
    model = er.train_expert_model(tmp_path, "production_brief")
    assert not model["ok"] and model["case_count"] == 1 and model["held_out_case_count"] == 0
    target = next((tmp_path / er.STORE).rglob("*.json"))
    payload = json.loads(target.read_text())
    payload["training_authorized"] = False
    target.write_text(json.dumps(payload))
    assert "digest" in er.train_expert_model(tmp_path, "production_brief")["reason"]


def test_review_cli_without_provider_can_return_advice_without_release(tmp_path):
    good = er.GOLDEN_SPECIMENS["production_brief"]["text"]
    for case in ("One", "Two", "Six"):
        record(tmp_path, good + "\n" + case, case, "pass")
        record(tmp_path, "TBD. No information. " + case, case, "fail")
    draft = tmp_path / "next.md"
    draft.write_text(good + "\nTen", encoding="utf-8")
    command = [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "bench",
               "judge", str(draft), "production_brief", "--root", str(tmp_path), "--json"]
    env = {**os.environ, "PATH": "", "HOME": str(tmp_path)}
    advise = subprocess.run([*command, "--advice-only"], capture_output=True, text=True, env=env)
    assert advise.returncode == 0, advise.stdout + advise.stderr
    assert json.loads(advise.stdout)["recommendation"] == "pass"
    release = subprocess.run(command, capture_output=True, text=True, env=env)
    assert release.returncode == 1
    assert json.loads(release.stdout)["verdict"] == "UNAVAILABLE"
    assert not (tmp_path / ".agents/ml_outcome_ratchet.json").exists()


def test_advice_abstention_keeps_revision_diagnostics(tmp_path):
    advice = er.assess_document("## Hypothesis\nA new proposal.", "research_note",
                                repo_root=tmp_path, include_audit=True)
    assert advice["recommendation"] == "abstain" and advice["requires_human_review"]
    assert not advice["ok"]
    audit = advice["mechanical_audit"]
    assert not audit["ok"]
    assert any("missing_grounding_citation" in v for v in audit["flow"]["violations"])
    assert "communications_strategist" in audit["board"]["blocking_roles"]
    assert "citation_grounding_mode:strict" in audit["recommended_levers"]
