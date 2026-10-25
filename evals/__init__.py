"""An independent evaluation engine. No DeepEval runtime dependency."""

__version__ = "0.2.0"


def __getattr__(name):
    if name in {"trace", "span", "observe"}:
        from evals import tracing
        return getattr(tracing, name)
    if name == "Store":
        from evals.storage import Store
        return Store
    raise AttributeError(name)
