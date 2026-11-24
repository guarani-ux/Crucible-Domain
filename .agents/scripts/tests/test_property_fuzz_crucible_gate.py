"""Zero-dependency stdlib property-based fuzzer for crucible_gate frontmatter & drift checks."""

from __future__ import annotations

import hashlib
import random
import string
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import crucible_gate as cg


def _rand_token(rng: random.Random, min_len: int = 1, max_len: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "_-./"
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(min_len, max_len)))


def test_fuzz_frontmatter_depends_on_and_sha256_200_cases(tmp_path: Path) -> None:
    rng = random.Random(20261123)
    valid_checked = 0
    malformed_checked = 0

    for i in range(220):
        md = tmp_path / f"case_{i}.md"
        kind = i % 4
        if kind == 0:
            # Valid block list + valid sha256 map
            deps = [f"Personal Work/doc_{j}_{_rand_token(rng, 2, 6).replace('/', '_')}.md" for j in range(rng.randint(1, 3))]
            hashes = {d: hashlib.sha256(d.encode("utf-8")).hexdigest() for d in deps}
            lines = ["---", "depends_on:"]
            lines.extend(f"  - {d}" for d in deps)
            lines.append("depends_on_sha256:")
            lines.extend(f"  {d}: {h}" for d, h in hashes.items())
            lines.extend(["---", "# Body"])
            md.write_text("\n".join(lines) + "\n", encoding="utf-8")

            parsed_deps = cg._extract_frontmatter_depends_on(md)
            parsed_hashes = cg._extract_frontmatter_depends_on_sha256(md)
            assert parsed_deps == deps
            assert parsed_hashes == hashes
            valid_checked += 1
        elif kind == 1:
            # Valid inline list
            deps = [f"Graphs/g_{j}.md" for j in range(rng.randint(1, 3))]
            md.write_text(f"---\ndepends_on: [{', '.join(deps)}]\n---\nBody\n", encoding="utf-8")
            assert cg._extract_frontmatter_depends_on(md) == deps
            assert cg._extract_frontmatter_depends_on_sha256(md) == {}
            valid_checked += 1
        elif kind == 2:
            # No frontmatter at all -> must return empty without crashing
            noise = "\n".join(_rand_token(rng, 0, 20) for _ in range(rng.randint(0, 5)))
            md.write_text(noise, encoding="utf-8")
            assert cg._extract_frontmatter_depends_on(md) == []
            assert cg._extract_frontmatter_depends_on_sha256(md) == {}
            malformed_checked += 1
        else:
            # Adversarial / malformed frontmatter (unclosed, unicode, colons, empty)
            junk = [
                "---",
                f"depends_on: {_rand_token(rng, 0, 10)}",
                f"  - {_rand_token(rng, 0, 10)}",
                "depends_on_sha256:",
                f"  {_rand_token(rng, 0, 8)}: {_rand_token(rng, 0, 8)}:{_rand_token(rng, 0, 4)}",
                "  no_colon_line",
                "other_key: [unclosed",
            ]
            if rng.random() < 0.5:
                junk.append("---")
            md.write_text("\n".join(junk), encoding="utf-8")
            parsed_deps = cg._extract_frontmatter_depends_on(md)
            parsed_hashes = cg._extract_frontmatter_depends_on_sha256(md)
            assert isinstance(parsed_deps, list)
            assert isinstance(parsed_hashes, dict)
            malformed_checked += 1

    assert valid_checked >= 100
    assert malformed_checked >= 100


def test_fuzz_artifact_dependencies_rejects_drift_and_traversal(tmp_path: Path) -> None:
    rng = random.Random(20261124)
    pw = tmp_path / "Personal Work"
    pw.mkdir()

    upstream = pw / "GROUND_TRUTH.md"
    upstream.write_text("baseline v1\n", encoding="utf-8")
    good_sha = cg._sha256_file(upstream)

    # 1. Valid pinned hash -> 0 failures, 0 warnings
    art_ok = pw / "ok.md"
    art_ok.write_text(
        f"---\ndepends_on_sha256:\n  Personal Work/GROUND_TRUTH.md: {good_sha}\n---\n# OK\n",
        encoding="utf-8",
    )
    fails, warns = cg._check_artifact_dependencies(tmp_path, strict=True)
    assert fails == []
    assert warns == []

    # 2. Traversal outside workspace & missing file -> always FAIL
    art_escape = pw / "escape.md"
    art_escape.write_text("---\ndepends_on:\n  - ../outside_secret.md\n  - Personal Work/missing_dep.md\n---\n", encoding="utf-8")
    fails_esc, _ = cg._check_artifact_dependencies(tmp_path, strict=False)
    assert any("resolves outside workspace" in f for f in fails_esc)
    assert any("missing" in f for f in fails_esc)
    art_escape.unlink()

    # 3. Stale hash -> WARN in non-strict, FAIL in strict
    bad_sha = hashlib.sha256(f"mutated-{rng.randint(1, 99999)}".encode("utf-8")).hexdigest()
    art_stale = pw / "stale.md"
    art_stale.write_text(
        f"---\ndepends_on_sha256:\n  Personal Work/GROUND_TRUTH.md: {bad_sha}\n---\n",
        encoding="utf-8",
    )
    fails_soft, warns_soft = cg._check_artifact_dependencies(tmp_path, strict=False)
    assert fails_soft == []
    assert any("content hash changed" in w for w in warns_soft)

    fails_strict, _ = cg._check_artifact_dependencies(tmp_path, strict=True)
    assert any("content hash changed" in f for f in fails_strict)
