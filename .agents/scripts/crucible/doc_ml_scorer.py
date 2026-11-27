#!/usr/bin/env python3
"""Layer 2: 100% Offline 40-Feature White-Box Local ML Document Scorer.

Pure Python (zero external ML packages, zero LLM calls, zero cloud quota).
Extracts 40 deterministic document-flow, craft, custody, strategic-charter, and
6-role stakeholder buy-in features, trains an L2-regularized logistic regression
model on golden specimens + mutation faults + human pass/fail labels, and outputs
explainable feature attributions and discrete control levers.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .doc_flow_engine import (
    GOLDEN_SPECIMENS,
    MUTATION_CATALOG,
    OrganizationCharter,
    UNAUTHORIZED_RELEASE_RE,
    evaluate_document_flow,
    evaluate_stakeholder_board,
    parse_document_ast,
)

FEATURE_NAMES: tuple[str, ...] = (
    # A. Structural & Information Flow (10)
    "word_count_norm",
    "section_count_norm",
    "table_count_norm",
    "table_row_density",
    "decision_position_ratio",
    "signal_before_hypothesis",
    "flow_score",
    "flow_violation_count_norm",
    "has_markdown_headers",
    "preamble_ratio",
    # B. Writing Craft & Rhythm (10)
    "avg_sentence_words_norm",
    "short_sentence_ratio",
    "slop_density",
    "active_verb_density",
    "lexical_diversity",
    "bullet_list_density",
    "avg_wpm_norm",
    "wpm_over_budget",
    "avg_av_overlap",
    "timecode_contiguous",
    # C. Evidence & Custody (6)
    "citation_count_norm",
    "hold_count_norm",
    "hold_owner_ratio",
    "unowned_hold_flag",
    "unauthorized_release_flag",
    "has_next_action_cue",
    # D. Organization Strategic Charter (6)
    "matched_mandates_norm",
    "matched_promises_norm",
    "matched_values_commitments_norm",
    "lens_as_mandate_trap",
    "stale_prior_plan_trap",
    "vision_kpi_misuse",
    # E. 6-Role Executive & Organizational Buy-In Board (8)
    "role_media_production_manager",
    "role_marketing_manager",
    "role_communications_strategist",
    "role_marketing_and_engagement_director",
    "role_communications_director",
    "role_ceo",
    "board_score",
    "blocking_role_ratio",
)

assert len(FEATURE_NAMES) == 40

ACTIVE_VERB_RE = re.compile(
    r"\b(approve|recommend|book|reserve|grab|capture|trim|verify|confirm|build|test|measure|show|open|cut|align|assign|deliver)\b",
    re.IGNORECASE,
)


def extract_document_features(
    text: str,
    form_id: str,
    *,
    target_duration_s: int | None = None,
    repo_root: Path | None = None,
    charter: OrganizationCharter | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Extract the 40 normalized numeric features plus flow/board context."""
    ast = parse_document_ast(text)
    fe = evaluate_document_flow(text, form_id, target_duration_s=target_duration_s)
    bd = evaluate_stakeholder_board(
        text,
        form_id,
        flow_eval=fe,
        target_duration_s=target_duration_s,
        repo_root=repo_root,
        charter=charter,
    )
    lines = text.splitlines()
    total_lines = max(1, len(lines))
    total_table_rows = sum(max(0, len(t) - 1) for t in ast.tables)
    non_preamble = [s for s in ast.sections if s.level > 0]
    preamble_words = sum(s.word_count for s in ast.sections if s.level == 0)

    sentences = [
        s.strip()
        for s in re.split(r"[.!?]+", re.sub(r"\|.*?\|", " ", text))
        if len(s.strip()) > 3
    ]
    if sentences:
        sent_lens = [len(re.findall(r"\b[\w'-]+\b", s)) for s in sentences]
        short_sent_ratio = sum(1 for n in sent_lens if n <= 15) / len(sent_lens)
        active_verb_density = min(1.0, len(ACTIVE_VERB_RE.findall(text)) / max(1, len(sentences)))
    else:
        short_sent_ratio = 0.0
        active_verb_density = 0.0

    content_toks = re.findall(r"[a-z]{3,}", text.lower())
    lex_div = len(set(content_toks)) / len(content_toks) if content_toks else 0.0
    bullet_lines = sum(1 for ln in lines if re.match(r"^\s*[-*]\s+", ln))

    role_scores = {r.role_id: float(r.score) for r in bd.role_reviews}
    ca = bd.charter_alignment
    avg_wpm = float(fe.features.get("avg_wpm", 0.0))
    max_beat_wpm = float(fe.features.get("max_beat_wpm", 0.0))
    sig_pos = float(fe.features.get("signal_position_ratio", 0.0))
    hyp_pos = float(fe.features.get("hypothesis_position_ratio", 1.0))

    feats: dict[str, float] = {
        # A. Structural & Flow
        "word_count_norm": round(min(1.0, ast.total_words / 1000.0), 4),
        "section_count_norm": round(min(1.0, len(non_preamble) / 10.0), 4),
        "table_count_norm": round(min(1.0, len(ast.tables) / 3.0), 4),
        "table_row_density": round(min(1.0, total_table_rows / 10.0), 4),
        "decision_position_ratio": round(float(fe.features.get("decision_position_ratio", 0.15)), 4),
        "signal_before_hypothesis": 1.0 if sig_pos < hyp_pos else 0.0,
        "flow_score": round(float(fe.flow_score), 4),
        "flow_violation_count_norm": round(min(1.0, len(fe.violations) / 5.0), 4),
        "has_markdown_headers": 1.0 if len(non_preamble) >= 2 else 0.0,
        "preamble_ratio": round(preamble_words / max(1, ast.total_words), 4),
        # B. Craft & Rhythm
        "avg_sentence_words_norm": round(min(1.0, ast.avg_sentence_words / 30.0), 4),
        "short_sentence_ratio": round(short_sent_ratio, 4),
        "slop_density": round(min(1.0, ast.slop_hits / 3.0), 4),
        "active_verb_density": round(active_verb_density, 4),
        "lexical_diversity": round(lex_div, 4),
        "bullet_list_density": round(min(1.0, bullet_lines / total_lines), 4),
        "avg_wpm_norm": round(min(1.0, avg_wpm / 200.0), 4),
        "wpm_over_budget": 1.0 if (avg_wpm > 155.0 or max_beat_wpm > 175.0) else 0.0,
        "avg_av_overlap": round(float(fe.features.get("avg_av_overlap", 0.0)), 4),
        "timecode_contiguous": 1.0 if fe.features.get("timecode_contiguous", True) else 0.0,
        # C. Evidence & Custody
        "citation_count_norm": round(min(1.0, len(ast.citations) / 3.0), 4),
        "hold_count_norm": round(min(1.0, ast.hold_count / 3.0), 4),
        "hold_owner_ratio": round(float(fe.features.get("hold_owner_ratio", 1.0)), 4),
        "unowned_hold_flag": 1.0 if (ast.hold_count > 0 and float(fe.features.get("hold_owner_ratio", 1.0)) < 0.75) else 0.0,
        "unauthorized_release_flag": 1.0 if UNAUTHORIZED_RELEASE_RE.search(text) else 0.0,
        "has_next_action_cue": 1.0 if re.search(r"\b(next|owner|confirm|approve|book|reserve|test)\b", text, re.IGNORECASE) else 0.0,
        # D. Organization Strategic Charter
        "matched_mandates_norm": round(min(1.0, len(ca.get("matched_mandates", [])) / 3.0), 4),
        "matched_promises_norm": round(min(1.0, len(ca.get("matched_service_promises", [])) / 3.0), 4),
        "matched_values_commitments_norm": round(
            min(1.0, (len(ca.get("matched_values", [])) + len(ca.get("matched_commitments", []))) / 2.0), 4
        ),
        "lens_as_mandate_trap": 1.0 if ca.get("lens_as_mandate_trap") else 0.0,
        "stale_prior_plan_trap": 1.0 if ca.get("stale_prior_plan_trap") else 0.0,
        "vision_kpi_misuse": 1.0 if ca.get("vision_kpi_misuse") else 0.0,
        # E. 6-Role Buy-In Board
        "role_media_production_manager": round(role_scores.get("media_production_manager", 1.0), 4),
        "role_marketing_manager": round(role_scores.get("marketing_manager", 1.0), 4),
        "role_communications_strategist": round(role_scores.get("communications_strategist", 1.0), 4),
        "role_marketing_and_engagement_director": round(role_scores.get("marketing_and_engagement_director", 1.0), 4),
        "role_communications_director": round(role_scores.get("communications_director", 1.0), 4),
        "role_ceo": round(role_scores.get("ceo", 1.0), 4),
        "board_score": round(float(bd.board_score), 4),
        "blocking_role_ratio": round(len(bd.blocking_roles) / 6.0, 4),
    }
    meta = {
        "flow_eval": fe,
        "board_eval": bd,
        "levers": list(dict.fromkeys(fe.recommended_levers + bd.recommended_levers)),
    }
    return feats, meta


def _sigmoid(z: float) -> float:
    if z >= 35.0:
        return 1.0
    if z <= -35.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class WhiteBoxModel:
    version: str
    feature_names: list[str]
    means: list[float]
    stds: list[float]
    weights: list[float]
    bias: float
    train_samples: int
    human_label_count: int
    holdout_accuracy: float
    holdout_f1: float
    trained_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WhiteBoxModel":
        return cls(
            version=str(raw.get("version", "1.0")),
            feature_names=list(raw["feature_names"]),
            means=[float(x) for x in raw["means"]],
            stds=[float(x) for x in raw["stds"]],
            weights=[float(x) for x in raw["weights"]],
            bias=float(raw["bias"]),
            train_samples=int(raw.get("train_samples", 0)),
            human_label_count=int(raw.get("human_label_count", 0)),
            holdout_accuracy=float(raw.get("holdout_accuracy", 0.0)),
            holdout_f1=float(raw.get("holdout_f1", 0.0)),
            trained_at=str(raw.get("trained_at", "")),
        )


def default_model_path(repo_root: Path) -> Path:
    return Path(repo_root) / ".agents" / "doc_ml_model.json"


def default_human_labels_path(repo_root: Path) -> Path:
    return Path(repo_root) / ".agents" / "bench" / "human_labels.jsonl"


def append_human_label(
    repo_root: Path,
    file_path: Path,
    form_id: str,
    verdict: str,
    *,
    note: str = "",
) -> dict[str, Any]:
    """Record a human pass/fail label so offline ML training learns from real taste."""
    v = verdict.strip().lower()
    if v not in ("pass", "fail"):
        raise ValueError(f"verdict must be 'pass' or 'fail', got {verdict!r}")
    rel = file_path.relative_to(repo_root).as_posix() if file_path.is_relative_to(repo_root) else str(file_path)
    row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "file": rel,
        "form_id": form_id,
        "label": 1 if v == "pass" else 0,
        "verdict": v,
        "note": note,
    }
    lp = default_human_labels_path(repo_root)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with lp.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def iter_benchmark_documents() -> Iterator[tuple[str, str, int | None, int]]:
    """Yield benchmark text, form, target duration and expected label in training order."""
    for spec in GOLDEN_SPECIMENS.values():
        form_id = spec["form_id"]
        target_dur = spec.get("target_duration_s")
        text = spec["text"]

        yield text, form_id, target_dur, 1

        for mut_name, (forms, mut_fn) in MUTATION_CATALOG.items():
            if form_id not in forms:
                continue
            if mut_name == "truncate_runtime_half" and (target_dur is None or target_dur < 60):
                continue
            mutated = mut_fn(text)
            if mutated == text:
                continue
            yield mutated, form_id, target_dur, 0


def _build_training_dataset(
    repo_root: Path,
    *,
    charter: OrganizationCharter | None = None,
) -> tuple[list[list[float]], list[int], int]:
    """Build labeled 40-feature dataset from golden specimens, mutation faults, and human labels."""
    xs: list[list[float]] = []
    ys: list[int] = []
    human_count = 0

    for text, form_id, target_dur, label in iter_benchmark_documents():
        features, _ = extract_document_features(
            text, form_id, target_duration_s=target_dur, repo_root=repo_root, charter=charter
        )
        vector = [features[name] for name in FEATURE_NAMES]
        # Retain the benchmark's 3:1 weighting for golden examples versus mutations.
        for _ in range(3 if label else 1):
            xs.append(vector)
            ys.append(label)

    # Human labels (upweighted 4x because real stakeholder decisions are highest-signal)
    lp = default_human_labels_path(repo_root)
    if lp.is_file():
        for raw_ln in lp.read_text(encoding="utf-8", errors="replace").splitlines():
            if not raw_ln.strip():
                continue
            try:
                rec = json.loads(raw_ln)
                fpath = Path(rec["file"])
                if not fpath.is_absolute():
                    fpath = repo_root / fpath
                if not fpath.is_file():
                    continue
                txt = fpath.read_text(encoding="utf-8", errors="replace")
                f_h, _ = extract_document_features(
                    txt, str(rec["form_id"]), repo_root=repo_root, charter=charter
                )
                vec_h = [f_h[name] for name in FEATURE_NAMES]
                lbl = int(rec["label"])
                human_count += 1
                for _ in range(4):
                    xs.append(vec_h)
                    ys.append(lbl)
            except Exception:
                continue

    return xs, ys, human_count


def train_whitebox_model(
    repo_root: Path,
    *,
    save: bool = True,
    epochs: int = 250,
    lr: float = 0.25,
    l2: float = 0.02,
    seed: int = 42,
    charter: OrganizationCharter | None = None,
) -> dict[str, Any]:
    """Train L2-regularized white-box logistic regression offline and compute holdout metrics."""
    t0 = time.perf_counter()
    xs, ys, human_count = _build_training_dataset(repo_root, charter=charter)
    n = len(xs)
    d = len(FEATURE_NAMES)

    idxs = list(range(n))
    random.Random(seed).shuffle(idxs)
    split = max(1, int(n * 0.80))
    train_idx = idxs[:split]
    val_idx = idxs[split:] or idxs[:1]

    # Standardize on training split only
    means = [0.0] * d
    stds = [1.0] * d
    for j in range(d):
        col = [xs[i][j] for i in train_idx]
        m = sum(col) / len(col)
        var = sum((v - m) ** 2 for v in col) / len(col)
        means[j] = m
        stds[j] = math.sqrt(var) if var > 1e-12 else 1.0

    def _norm(row: list[float]) -> list[float]:
        return [(row[j] - means[j]) / stds[j] for j in range(d)]

    x_train = [_norm(xs[i]) for i in train_idx]
    y_train = [ys[i] for i in train_idx]
    x_val = [_norm(xs[i]) for i in val_idx]
    y_val = [ys[i] for i in val_idx]

    weights = [0.0] * d
    bias = 0.0
    m_train = max(1, len(x_train))

    for _ in range(epochs):
        grad_w = [0.0] * d
        grad_b = 0.0
        for row, y in zip(x_train, y_train):
            z = bias + sum(w * v for w, v in zip(weights, row))
            err = _sigmoid(z) - y
            grad_b += err
            for j in range(d):
                grad_w[j] += err * row[j]
        bias -= lr * (grad_b / m_train)
        for j in range(d):
            weights[j] -= lr * ((grad_w[j] / m_train) + l2 * weights[j])

    # Holdout evaluation
    tp = fp = tn = fn = 0
    for row, y in zip(x_val, y_val):
        p = _sigmoid(bias + sum(w * v for w, v in zip(weights, row)))
        pred = 1 if p >= 0.5 else 0
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 1 and y == 0:
            fp += 1
        elif pred == 0 and y == 0:
            tn += 1
        else:
            fn += 1

    acc = round((tp + tn) / max(1, len(y_val)), 4)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    f1 = round((2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0, 4)

    model = WhiteBoxModel(
        version="1.0",
        feature_names=list(FEATURE_NAMES),
        means=[round(v, 6) for v in means],
        stds=[round(v, 6) for v in stds],
        weights=[round(v, 6) for v in weights],
        bias=round(bias, 6),
        train_samples=n,
        human_label_count=human_count,
        holdout_accuracy=acc,
        holdout_f1=f1,
        trained_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )

    model_path = default_model_path(repo_root)
    if save:
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.write_text(json.dumps(model.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ranked_w = sorted(zip(FEATURE_NAMES, model.weights), key=lambda kv: kv[1], reverse=True)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "ok": acc >= 0.90,
        "elapsed_ms": elapsed_ms,
        "model_path": str(model_path),
        "feature_count": d,
        "train_samples": n,
        "human_label_count": human_count,
        "holdout_accuracy": acc,
        "holdout_f1": f1,
        "top_positive_weights": [(k, round(v, 3)) for k, v in ranked_w[:5]],
        "top_negative_weights": [(k, round(v, 3)) for k, v in ranked_w[-5:][::-1]],
    }


def load_or_train_model(repo_root: Path) -> WhiteBoxModel:
    mp = default_model_path(repo_root)
    if mp.is_file():
        try:
            raw = json.loads(mp.read_text(encoding="utf-8", errors="replace"))
            if len(raw.get("feature_names", [])) == len(FEATURE_NAMES):
                return WhiteBoxModel.from_dict(raw)
        except Exception:
            pass
    train_whitebox_model(repo_root, save=True)
    return WhiteBoxModel.from_dict(json.loads(mp.read_text(encoding="utf-8", errors="replace")))


def score_document_ml(
    text: str,
    form_id: str,
    *,
    repo_root: Path,
    target_duration_s: int | None = None,
    charter: OrganizationCharter | None = None,
    model: WhiteBoxModel | None = None,
) -> dict[str, Any]:
    """Score a document offline with the 40-feature white-box ML model and return feature attributions."""
    mdl = model or load_or_train_model(repo_root)
    feats, meta = extract_document_features(
        text,
        form_id,
        target_duration_s=target_duration_s,
        repo_root=repo_root,
        charter=charter,
    )
    contribs: list[tuple[str, float, float]] = []
    z = mdl.bias
    for name, mean, std, weight in zip(mdl.feature_names, mdl.means, mdl.stds, mdl.weights):
        val = float(feats.get(name, 0.0))
        z_val = (val - mean) / (std if std > 1e-12 else 1.0)
        c = weight * z_val
        z += c
        contribs.append((name, round(c, 4), round(val, 4)))

    prob = round(_sigmoid(z), 4)
    pos_drivers = sorted([c for c in contribs if c[1] > 0], key=lambda x: -x[1])[:5]
    neg_drivers = sorted([c for c in contribs if c[1] < 0], key=lambda x: x[1])[:5]
    fe = meta["flow_eval"]
    bd = meta["board_eval"]
    verdict = "PASS" if (prob >= 0.5 and bd.buy_in_ready and fe.passed) else "FAIL"

    return {
        "ok": verdict == "PASS",
        "form_id": form_id,
        "verdict": verdict,
        "buy_in_probability": prob,
        "flow_score": fe.flow_score,
        "board_score": bd.board_score,
        "blocking_roles": bd.blocking_roles,
        "top_positive_drivers": [{"feature": n, "contribution": c, "value": v} for n, c, v in pos_drivers],
        "top_negative_drivers": [{"feature": n, "contribution": c, "value": v} for n, c, v in neg_drivers],
        "recommended_levers": meta["levers"],
    }
