"""Local, form-specific editorial triage from permissioned professional decisions.

The nearest-centroid classifier uses the existing 40 measured document features.
Examples retain the decision's provenance and feature snapshot, never the draft.
Model advice has no authority to approve a document or award reviewer axis scores.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from functools import cache
from pathlib import Path
from statistics import fmean
from typing import Any, BinaryIO

from .doc_flow_engine import GOLDEN_SPECIMENS
from .doc_ml_scorer import FEATURE_NAMES, extract_document_features, iter_benchmark_documents
from .judgment_panel import JudgmentVerdict

FORMS = {spec["form_id"] for spec in GOLDEN_SPECIMENS.values()}
VERDICTS = ("pass", "fail")
STORE = Path(".agents/bench/expert_reviews")
FEATURE_SCHEMA = "document-features-40-v1"


@cache
def _benchmark_digests() -> frozenset[str]:
    # Historical records retain only the raw digest. Cover ordinary editor serializations.
    return frozenset(
        hashlib.sha256(version.encode(encoding)).hexdigest()
        for text, _, _, _ in iter_benchmark_documents()
        for version in (text, text.replace("\n", "\r\n"))
        for encoding in ("utf-8", "utf-8-sig")
    )


def _features(text: str, form_id: str, root: Path) -> list[float]:
    features, _ = extract_document_features(text, form_id, repo_root=root)
    return [features[key] for key in FEATURE_NAMES]


def _validate(row: dict[str, Any]) -> None:
    if row["training_authorized"] is not True or row["form_id"] not in FORMS or row["verdict"] not in VERDICTS:
        raise ValueError("Expected authorized training use, a supported document form and a pass/fail decision")
    for field in ("reviewer", "role", "evidence", "case_id"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"Missing professional review field: {field}")
    digest = row["document_sha256"]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid document digest")
    values = row["features"]
    if row["feature_schema"] != FEATURE_SCHEMA or len(values) != len(FEATURE_NAMES):
        raise ValueError("Unsupported document feature schema")
    if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
        raise ValueError("Invalid document features")


def _lock_writer(handle: BinaryIO) -> None:
    """Serialize local writers until the handle closes, including after process exit."""
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX)


def append_expert_label(repo_root: Path, file_path: Path, form_id: str, verdict: str, *,
                       reviewer: str, role: str, case_id: str, evidence: str,
                       training_authorized: bool) -> dict[str, Any]:
    """Record a human curator's attestation for this exact revision and review."""
    if training_authorized is not True:
        raise ValueError("Training permission for this document and review is required")
    if form_id not in FORMS:
        raise ValueError(f"Unsupported document form: {form_id}")
    content = file_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest in _benchmark_digests():
        raise ValueError("Benchmark documents cannot be used as professional training cases")
    text = content.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("Document is empty")
    row = dict(form_id=form_id, verdict=verdict.strip().lower(), reviewer=reviewer.strip(),
               role=role.strip(), case_id=case_id.strip(), evidence=evidence.strip(),
               training_authorized=True, document_sha256=digest,
               feature_schema=FEATURE_SCHEMA, features=_features(text, form_id, repo_root))
    _validate(row)
    payload = json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
    directory = repo_root / STORE / form_id
    directory.mkdir(parents=True, exist_ok=True)
    # Content-addressed immutable examples make repeated or concurrent imports idempotent.
    target = directory / (hashlib.sha256(payload).hexdigest() + ".json")
    with (directory / ".writer.lock").open("a+b") as lock:
        _lock_writer(lock)
        try:
            _load(repo_root, form_id, pending=row)
        except (TypeError, KeyError, OverflowError) as exc:
            raise ValueError(f"Invalid professional review data: {exc}") from exc
        if not target.exists():
            descriptor, temporary = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                os.replace(temporary, target)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return {key: value for key, value in row.items() if key != "features"}


def _load(root: Path, form_id: str, *, pending: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if form_id not in FORMS:
        raise ValueError(f"Unsupported document form: {form_id}")
    documents: dict[str, dict[str, Any]] = {}

    def register(row: dict[str, Any]) -> None:
        old = documents.setdefault(row["document_sha256"], row)
        if any(old[k] != row[k] for k in ("case_id", "verdict", "features")):
            raise ValueError("Conflicting reviews or case identities for one document revision")

    for path in sorted((root / STORE / form_id).glob("*.json")):
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != path.stem:
            raise ValueError("Expert review record does not match its digest")
        row = json.loads(payload)
        _validate(row)
        if row["form_id"] != form_id:
            raise ValueError("Expert review filed under the wrong form")
        if row["document_sha256"] not in _benchmark_digests():
            register(row)
    if pending is not None:
        register(pending)
    return list(documents.values())


def _fit(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    # Give each assignment equal weight within its class, regardless of revisions.
    groups: dict[tuple[str, str], list[list[float]]] = defaultdict(list)
    for r in rows:
        groups[(r["verdict"], r["case_id"])].append(r["features"])
    samples: dict[str, list[list[float]]] = defaultdict(list)
    for (label, _), group in groups.items():
        samples[label].append([fmean(values) for values in zip(*group)])
    return {label: [fmean(values) for values in zip(*group)] for label, group in samples.items()}


def _classify(centers: dict[str, list[float]], features: list[float]) -> tuple[str, float]:
    distances = sorted((math.dist(vector, features), label) for label, vector in centers.items())
    if math.isclose(distances[0][0], distances[1][0], abs_tol=1e-10):
        return "abstain", distances[0][0]
    return distances[0][1], distances[0][0]


def _train(root: Path, form_id: str) -> tuple[dict, dict, dict]:
    info = dict(ok=False, form_id=form_id, case_count=0, held_out_case_count=0,
                class_recall={}, reason="")
    try:
        rows = _load(root, form_id)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        info["reason"] = f"Invalid professional review data: {exc}"
        return info, {}, {}
    cases = {r["case_id"] for r in rows}
    info["case_count"] = len(cases)
    if any(len({r["case_id"] for r in rows if r["verdict"] == label}) < 2 for label in VERDICTS):
        info["reason"] = "Need pass and fail decisions for this form, each represented by at least two independent assignments."
        return info, {}, {}

    recall: dict[str, list[float]] = defaultdict(list)
    radii = dict.fromkeys(VERDICTS, 0.0)
    for case in sorted(cases):
        centers = _fit([r for r in rows if r["case_id"] != case])
        by_label: dict[str, list[bool]] = defaultdict(list)
        for row in rows:
            if row["case_id"] == case:
                prediction, distance = _classify(centers, row["features"])
                label = row["verdict"]
                by_label[label].append(prediction == label)
                if prediction == label:
                    radii[label] = max(radii[label], distance)
        for label, hits in by_label.items():
            recall[label].append(fmean(hits))
    info.update(held_out_case_count=len(cases), class_recall={k: fmean(v) for k, v in recall.items()})
    # Provisional triage only. Each class must beat chance on unseen assignments.
    if min(info["class_recall"].values()) <= 0.5:
        info["reason"] = "Held-out professional decisions were not distinguished for both classes."
        return info, {}, {}
    info.update(ok=True, reason="Per-form advisory qualified on held-out assignments.")
    return info, _fit(rows), radii


def train_expert_model(repo_root: Path, form_id: str) -> dict[str, Any]:
    """Fit and report leave-one-assignment-out results from the current evidence."""
    info, _, _ = _train(repo_root, form_id)
    return info


def assess_document(text: str, form_id: str, *, repo_root: Path, include_audit: bool = False) -> dict[str, Any]:
    info, centers, radii = _train(repo_root, form_id)
    result = {**info, "recommendation": "abstain", "requires_human_review": True}
    if not info["ok"] and not (include_audit and form_id in FORMS):
        return result
    features, context = extract_document_features(text, form_id, repo_root=repo_root)
    if include_audit:
        flow = context["flow_eval"]
        board = context["board_eval"]
        result["mechanical_audit"] = {
            "ok": flow.passed and board.buy_in_ready,
            "flow": flow.to_dict(),
            "board": board.to_dict(),
            "recommended_levers": context["levers"],
        }
    if info["ok"]:
        prediction, distance = _classify(centers, [features[key] for key in FEATURE_NAMES])
        if prediction == "abstain" or distance > radii[prediction] + 1e-10:
            result.update(ok=False, reason="Ambiguous or outside validated feature distances.")
        else:
            result["recommendation"] = prediction
    return result


def review_document(text: str, form_id: str, *, repo_root: Path, **kwargs: Any) -> JudgmentVerdict:
    advisory = assess_document(text, form_id, repo_root=repo_root)
    return JudgmentVerdict(ok=False, verdict="UNAVAILABLE", judgment_score=0.0,
                           raw_error=advisory["reason"] + " Professional review required for sign-off.",
                           advisory=advisory)
