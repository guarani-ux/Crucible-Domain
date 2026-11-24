"""Selective BM25/exact/binding router for Crucible Domain capabilities."""

from __future__ import annotations

import math
import re
from typing import Any

from .models import (
    CHATGPT_SKILL_BINDINGS,
    STOPWORDS,
    TOKEN_RE,
    CapabilityIndex,
    RouteMatch,
    RouteResult,
)


CAPABILITY_PRECEDENCE: dict[str, int] = {
    "entry_doc": 0,
    "procedure": 1,
    "role": 2,
    "skill": 3,
    "primitive": 4,
    "knowledge": 5,
    "project": 6,
    "exhibit": 7,
}


def _tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS and len(tok) > 1]


def _extract_chatgpt_skill_id(query: str) -> str | None:
    q = query.strip()
    if q in CHATGPT_SKILL_BINDINGS:
        return q
    m = re.search(r"skill_id=([0-9a-f]{24,40})", q, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _score_entries(
    index: CapabilityIndex,
    q_tokens: list[str],
    *,
    min_score: float = 1.5,
    include_deep_fields: bool = False,
    ledger: dict[str, Any] | None = None,
) -> list[RouteMatch]:
    doc_tokens_map: dict[str, tuple[set[str], set[str], set[str]]] = {}
    df: dict[str, int] = {}
    for eid, entry in index.entries.items():
        title_toks = set(_tokenize(f"{entry.id} {entry.title}"))
        use_toks = set(_tokenize(f"{entry.use_when} {entry.domain} {entry.kind}"))
        body_source = (
            f"{entry.summary} {entry.mechanisms} {entry.breakpoints} {entry.transfers} {entry.limit_or_action}"
            if include_deep_fields
            else entry.summary
        )
        body_toks = set(_tokenize(body_source))
        doc_tokens_map[eid] = (title_toks, use_toks, body_toks)
        for tok in title_toks | use_toks | body_toks:
            df[tok] = df.get(tok, 0) + 1

    n_docs = max(1, len(index.entries))
    q_unique = set(q_tokens)
    scored: list[RouteMatch] = []
    for eid, entry in index.entries.items():
        title_toks, use_toks, body_toks = doc_tokens_map[eid]
        score = 0.0
        hit_tokens: list[str] = []
        for qtok in q_unique:
            idf = math.log(1.0 + (n_docs - df.get(qtok, 0) + 0.5) / (df.get(qtok, 0) + 0.5))
            weight = 0.0
            if qtok in title_toks:
                weight += 3.0
            if qtok in use_toks:
                weight += 2.0
            if qtok in body_toks:
                weight += 1.0
            if weight > 0:
                score += idf * min(weight, 4.0)
                hit_tokens.append(qtok)
        if score > 0 and entry.kind == "procedure" and len(hit_tokens) >= 2:
            score += 0.5
        if score >= min_score:
            prior_mult = 1.0
            adj_score = score * prior_mult
            via = "tokens:" + ",".join(sorted(hit_tokens))
            if prior_mult != 1.0:
                via += f" (prior={prior_mult:.2f}x)"
            scored.append(
                RouteMatch(
                    entry=entry,
                    score=adj_score,
                    matched_via=via,
                )
            )

    scored.sort(
        key=lambda m: (
            -round(m.score, 6),
            CAPABILITY_PRECEDENCE.get(m.entry.kind, 99),
            m.entry.id,
        )
    )
    return scored


def route_query(
    index: CapabilityIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 1.5,
    ledger: dict[str, Any] | None = None,
) -> RouteResult:
    """Resolve an ID, ChatGPT skill_id, or natural-language task in RAM with selective abstention."""
    raw = query.strip()
    if not raw:
        return RouteResult(query=query, match_mode="abstained", abstained=True, reason="Empty query.", matches=[])

    # 1. ChatGPT skill_id or URL resolution
    cgpt_id = _extract_chatgpt_skill_id(raw)
    if cgpt_id is not None:
        binding = index.chatgpt_bindings.get(cgpt_id)
        if binding:
            matches = [
                RouteMatch(entry=index.entries[tid], score=100.0, matched_via=f"chatgpt_skill:{cgpt_id} ({binding.label})")
                for tid in binding.target_ids
                if tid in index.entries
            ]
            if matches:
                return RouteResult(
                    query=query,
                    match_mode="chatgpt_binding",
                    abstained=False,
                    reason=f"Bound ChatGPT skill '{binding.label}' ({cgpt_id}) to {len(matches)} local target(s).",
                    matches=matches,
                )

    # 2. Exact canonical ID / skill name lookup (O(1))
    norm_key = raw.lower()
    if norm_key in index.alias_map:
        canon_id = index.alias_map[norm_key]
        primary = index.entries[canon_id]
        matches = [RouteMatch(entry=primary, score=100.0, matched_via="exact_id")]
        for rel_id in primary.related_ids[: max(0, top_k - 1)]:
            if rel_id in index.entries:
                matches.append(RouteMatch(entry=index.entries[rel_id], score=10.0, matched_via=f"linked_from:{canon_id}"))
        return RouteResult(
            query=query,
            match_mode="exact",
            abstained=False,
            reason=f"Resolved canonical ID {canon_id}.",
            matches=matches,
        )

    # 3. BM25-weighted lexical scoring with field boosts
    q_tokens = _tokenize(raw)
    if not q_tokens:
        return RouteResult(
            query=query,
            match_mode="abstained",
            abstained=True,
            reason="Query had no domain-bearing tokens; act directly or inspect README.md.",
            matches=[],
        )

    scored = _score_entries(index, q_tokens, min_score=min_score, include_deep_fields=False, ledger=ledger)
    top_matches = scored[:top_k]
    if not top_matches:
        return RouteResult(
            query=query,
            match_mode="abstained",
            abstained=True,
            reason=f"No capability reached confidence threshold ({min_score}); act directly without forcing a skill.",
            matches=[],
        )

    return RouteResult(
        query=query,
        match_mode="lexical",
        abstained=False,
        reason=f"Matched {len(top_matches)} local capability item(s) in {index.build_ms:.1f}ms.",
        matches=top_matches,
    )


def _format_route_text(result: RouteResult) -> str:
    if result.abstained:
        return f"ABSTAINED: {result.reason}"
    lines = [f"[{result.match_mode}] {result.reason}"]
    for idx, match in enumerate(result.matches, 1):
        e = match.entry
        loc = f"{e.path}:{e.line}" if e.line > 1 else e.path
        lines.append(f"{idx}. {e.id} ({e.kind}, {e.reachability}, score={match.score:.2f}) — {e.title}")
        lines.append(f"   Open: {loc}")
        if e.summary:
            lines.append(f"   Note: {e.summary[:180]}")
        if e.related_ids:
            lines.append(f"   Linked: {', '.join(e.related_ids[:8])}")
    return "\n".join(lines)
