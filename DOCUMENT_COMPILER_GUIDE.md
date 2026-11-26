# Compiling and reviewing documents

Crucible renders a source-backed document graph using local Python. The author supplies the facts, wording and project decisions. The compiler checks the graph and renders Markdown. A qualified professional retains editorial and release authority.

## Compile a real document

Install the repository requirements with `python -m pip install -r requirements.txt`. From the project root, run the following with a graph for the indicated form.

```sh
python .agents/scripts/crucible_gate.py bench compile youtube 180 --form research_note --from-json graph.json --mode local --json
```

Inspect the rendered `markdown`, graph validation and `gate2` fields separately. A mechanically valid document can still need professional review. Use `--no-judge` for a mechanical check. Supported forms are `av_script`, `production_brief`, `leadership_report`, `research_note`, `treatment`, `call_sheet`, `shot_list`, and `content_calendar`. To inspect an example graph for a form, run the same command with `--mode offline` and omit `--from-json`. Offline examples contain illustrative content. Use the governing project sources to prepare a real graph.

For an existing Markdown draft, use `bench judge DOCUMENT FORM --advice-only --json` for a triage recommendation, or omit `--advice-only` to check professional sign-off with the same Python entry point. For a document pack, use `bench pipeline --mode local --documents-dir DIR`. Place each supplied document under `DIR/<project-id>/<manifest filename>`. The [pipeline manifest](.agents/bench/pipelines.yaml) identifies the stage filenames.

## Learn from professional decisions

A curator records the exact revision a professional reviewed, their decision, the assignment, and a reference supporting their role and decision. Obtain permission for training use. Keep revisions from one assignment under the same case ID. Examples of relevant judgments include an editor deciding whether a research note separates observations from hypotheses, or a producer deciding whether a brief contains enough information to commission a shoot.

```sh
python .agents/scripts/crucible_gate.py bench label-expert draft.md research_note fail --reviewer "$REVIEWER" --role "$ROLE" --case-id "$ASSIGNMENT" --evidence "$REVIEW_RECORD" --training-authorized --json
python .agents/scripts/crucible_gate.py bench judge next-draft.md research_note --advice-only --json
```

A successful label receipt includes `training_readiness` for that form. If `training_readiness.ok` is false, read its reason to see why the classifier abstains. The advice command can still return mechanical diagnostics. When it is true, run the advice command on the next draft. To inspect readiness separately, run `bench train-expert FORM --json`.

The classifier learns per form from local records containing measured features, a document digest and the review provenance. Training checks predictions on held-out assignments, including both pass and fail decisions. Read the case counts and results for each class before interpreting a recommendation. Missing evidence, inadequate performance, ambiguous inputs or a document outside the measured range lead to abstention. A recommendation can help prioritize revisions. It supplies neither claim evidence nor a professional's sign-off. The separate benchmark trainer uses fixtures and mutations to exercise the software.

Review the [form protocols](.agents/bench/craft_protocols.yaml), [judgment rubrics](.agents/bench/judgment_rubrics.yaml), and controlling project materials for the intended audience and next action.
