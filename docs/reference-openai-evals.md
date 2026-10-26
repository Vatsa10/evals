# OpenAI Evals reference and applied ideas

Cloned [openai/evals](https://github.com/openai/evals) into ignored
`.upstream/openai-evals` at commit
`8eac7a7de5215c907fbddc30efdaf316913eccdd`. LFS dataset downloading was stopped
after code checkout; remaining datasets are pointers. We reviewed code/docs
without installing or importing its runtime. Both projects use Python module
name `evals`; do not install OpenAI's `evals` distribution in the same interpreter
as `evals-framework`.

| Reference reviewed | Applied here |
| --- | --- |
| [Completion functions](https://github.com/openai/evals/blob/8eac7a7de5215c907fbddc30efdaf316913eccdd/docs/completion-fns.md) | Application adapter remains independent of grading; the verifier uses a container invoker without importing app code into its process |
| [Dataset construction/versioning](https://github.com/openai/evals/blob/8eac7a7de5215c907fbddc30efdaf316913eccdd/docs/build-eval.md) | Strict input/ideal JSONL import, stable identities, source hashes and name.split.version labels |
| [Registry](https://github.com/openai/evals/blob/8eac7a7de5215c907fbddc30efdaf316913eccdd/evals/registry.py) | Explicit public/holdout suite lists in a pinned grading repository |
| [Recorder](https://github.com/openai/evals/blob/8eac7a7de5215c907fbddc30efdaf316913eccdd/evals/record.py) | Private trial evidence and separate public aggregate decisions |
| [Judge meta-evaluation](https://github.com/openai/evals/blob/8eac7a7de5215c907fbddc30efdaf316913eccdd/docs/build-eval.md) | Pinned custom grader dependencies; subjective judges still need independent human-labeled calibration |

The security architecture implements the user's requested verifier design;
these are not security guarantees inherited from OpenAI Evals. No upstream
code or benchmark samples were copied into our runtime.

```console
evals import-openai samples.jsonl --name support --split dev --dataset-version v1 --adapter app/adapter.py --output evaluations/support.json
evals validate evaluations/support.json
```

The adapter is relative to the generated suite directory. Import makes no model
calls and permits an adapter that has not been wired yet; validation checks the
real integration before execution. Input message arrays remain intact. A single
string `ideal` becomes an exact-match grader. Explicit IDs are preserved;
otherwise IDs derive from sample content. Duplicate identities, malformed JSON,
extra fields and non-string ideals are rejected before writing a partial suite.

YAML registries, completion classes, alternative answers, fuzzy-match semantics,
model-graded rubrics and solver APIs are not translated implicitly. Write
explicit graders for them. Changing data or criteria requires a new reviewed
contract and baseline. Public examples alone cannot detect overfitting; use
[private holdouts in the external verifier](isolated-verifier.md).
