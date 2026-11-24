#!/usr/bin/env pwsh
$HubRoot = Split-Path -Parent $PSScriptRoot
$py = @'
import concurrent.futures, pathlib, subprocess, sys, time
HUB = sys.argv[1]
SPOKE = "C:/crucible-spokes/story-lane"
sys.path.insert(0, str(pathlib.Path(HUB, ".agents/scripts")))
try:
    import ram_ml_engine
    ml_rank = ram_ml_engine.rank_tests_for_changes(pathlib.Path(HUB))
    test_files = [pathlib.Path(HUB, r["test_path"]) for r in ml_rank["ranked_tests"]]
    impacted_set = {r["test_path"] for r in ml_rank["ranked_tests"] if r["tier"] == "impacted"}
    ml_note = f"ML test-ranker: {ml_rank['impacted_count']}/{len(test_files)} impacted ({ml_rank['elapsed_ms']}ms, source={ml_rank['change_source']})"
except Exception:
    test_files = sorted(pathlib.Path(HUB, ".agents/scripts/tests").glob("test_*.py"))
    impacted_set = set()
    ml_note = "ML test-ranker: fallback alphabetical"
STEPS = [
    ("Hub Gate (--strict)", HUB,   ["python", ".agents/scripts/crucible_gate.py", "check", "--strict"]),
    ("Hub Doctor",          HUB,   ["python", ".agents/scripts/crucible_gate.py", "doctor"]),
    ("Story-Lane Pytest",   SPOKE, ["python", "-m", "pytest", "tests/test_storylane_spoke_mcp.py", "tests/test_storylane_fuzz_and_replay.py", "-q"]),
] + [(f"Pytest:{f.stem}{'*' if f.relative_to(HUB).as_posix() in impacted_set else ''}", HUB, ["pytest", str(f), "-q"]) for f in test_files]

def run_step(item):
    name, cwd, cmd = item
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
        return name, p.returncode, time.perf_counter() - t0, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired as exc:
        return name, 124, time.perf_counter() - t0, f"TIMEOUT after 60s: {exc}"

t_all = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=len(STEPS)) as pool:
    results = list(pool.map(run_step, STEPS))
wall = time.perf_counter() - t_all
failed = 0
print("\n=== Crucible Terminal Verification Summary (16-Core Parallel) ===")
print(ml_note)
print(f"{'Check':<34} {'Status':<8} {'Seconds':>7}")
print(f"{'-'*34} {'-'*8} {'-'*7}")
for name, rc, secs, out in results:
    status = "PASS" if rc == 0 else "FAIL"
    print(f"{name:<34} {status:<8} {secs:>7.2f}")
    if rc != 0:
        failed += 1
        print(f"\n--- FAILED: {name} (exit {rc}) ---\n{out}\n")
print(f"\nWall-clock: {wall:.2f}s ({len(results)} parallel checks)")
try:
    ram_ml_engine.record_verify_outcomes(
        pathlib.Path(HUB),
        ml_rank.get("changed_files", []),
        [(name, rc) for name, rc, _, _ in results],
    )
except Exception:
    pass
if failed:
    print(f"RESULT: {failed} check(s) FAILED")
    sys.exit(1)
print(f"RESULT: ALL {len(results)} CHECKS PASSED")
'@
$py | python - $HubRoot
exit $LASTEXITCODE
