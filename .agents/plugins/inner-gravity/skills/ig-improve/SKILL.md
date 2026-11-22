---
name: ig-improve
description: Turn an observed miss, correction, counterexample, or gain into a reviewed and testable change to the agent's method or configuration.
---

1. Capture the actual trace or artifact and what consequence mattered. Distinguish failure to notice, retrieve, infer, execute, verify, or hand off. Preserve neutral results and the limits of any successful case.
2. Propose the smallest change that could address the cause. Define a realistic test that would have caught the failure, a routine control, and what a regression would look like. Keep the scoring key out of worker prompts.
3. Run current and candidate configurations against the same task, source versions, permissions, model, and budget when feasible. Score the outcome and the trace separately. Record which host actually ran. Repeat consequential cases before generalizing.
4. Prefer an update to an existing applicable rule or skill. Antigravity's /learn, when present, can draft the change for review. Record the diff, supporting and contrary evidence, scope and rollback. Promote only through existing project authority. Leave the next run enough evidence to reverse it.
