# External patch verification

Local `improve check/finish` hashes are in-session drift checks. An agent with
write access can change local state. Never call that an adversarial trust
boundary. Local decisions explicitly identify the `in_session` trust profile.

For agent-resistant verification, establish a separately controlled runner,
private contract repository and independently distributed public signing key.
The coding agent must not have that runner's shell, Docker socket, workflow
edits, contract, key or secrets. Do not generate a purported production signing
key inside the agent workspace. Prepare the application patch with:

```text
evals verifier submit --source-repo . --source-ref FULL_ORIGINAL_COMMIT --allow app --output .evals/candidate.patch
```

The remote contract has its own application allowlist. Tests, graders,
conftest/pytest files, CI/Git files, fixtures, snapshots, startup hooks, test
config and lockfiles cannot be patched. Renames, copies, binaries, symlinks and
submodules are rejected. Use `git add -N` for intended new app files; don't omit
changes or modify the baseline to ease grading.

The trusted operator runs `evals verifier check` or `evals verifier finish`,
supplying pinned source/contract commits, patch, protected private key, review,
unique request ID and fresh output folder. Both recompute baseline and candidate
from source. The entire grading repository is hashed. Private holdouts differ
from public inputs. Grading stays outside fresh non-root target containers;
the target receives only application files, minimal adapter code, input/context.

This isolated profile uses native suites, Python JSON adapters and Docker with
no network. It has no pytest backend or live API gateway. For network-dependent
targets, explain the limitation and establish the needed gateway with the
operator. Do not silently fall back and call local execution isolated. The
normal local live-provider workflow remains available when its trust profile
satisfies the request.

Review is required by default: a trusted human/LLM/operator input bound to the
patch SHA256, never an agent-created self-approval. Review hardcoding, broad
exception swallowing, disabled assertions and runner edits. Heuristics are
advisory. Passing execution without required review yields `needs_review`;
failed checks yield `not_verified`; invalid input yields `rejected`.

Publish only signed `decision.json`; `private/` reports contain holdouts.
Authenticate using an independently trusted public key:

```text
evals verifier verify-decision decision.json --public-key TRUSTED_PUBLIC_KEY --patch .evals/candidate.patch --source-ref FULL_ORIGINAL_COMMIT --contract-ref FULL_CONTRACT_COMMIT --request-id CURRENT_REQUEST_ID
```

Require an eligible decision for the expected patch, refs and ID. The operator
issues/retires IDs and controls total attempt/spend budgets; per-submission call
caps are not a distributed nonce service or ledger. Never substitute an unsigned
local decision or upload the entire result directory. If external infrastructure
is not configured, report the patch and missing deployment requirements.

Operator guide: https://github.com/Vatsa10/evals/blob/main/docs/isolated-verifier.md
