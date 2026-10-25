# Five-system application lab

See the [complete guide](../../docs/production-lab.md) for the scenario matrix,
architecture, live and CI commands, trace inspection, and measurement limits.

```console
python scripts/production_lab.py --workspace .evals/live-lab --model live
```

Run from the repository root. Live mode requires your existing Claude Code login
and uses its configured model. `--model fixture` is an explicitly labeled
deterministic integration check. The lab has synthetic data and real local
HTTP/SQLite side effects; it does not contact customer systems.
