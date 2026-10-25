"""Context-local spans with synchronous local persistence and optional online graders."""

from contextvars import ContextVar
from functools import wraps
import inspect
import json
import time
import uuid
import warnings

from evals.monitoring import record_trace
from evals.storage import Store, utc_now


_current_trace = ContextVar("evals_trace", default=None)
_current_span = ContextVar("evals_span", default=None)


def json_safe(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False,
                                    default=lambda item: {"python_type": type(item).__name__}))
    except (TypeError, ValueError):
        return {"python_type": type(value).__name__}


class trace:
    """Record one request. Call update() with output/state/messages you want graded."""

    def __init__(self, name, *, input=None, thread_id=None, store=None, policy=None, root=None):
        self.store, self.policy, self.root = store, policy, root
        self.record = {"id": uuid.uuid4().hex, "name": name, "thread_id": thread_id,
                       "input": json_safe(input), "observation": {}, "spans": []}

    def __enter__(self):
        self.record["started_at"] = utc_now()
        self.timer = time.perf_counter()
        self.token = _current_trace.set(self)
        self.span_token = _current_span.set(None)
        return self

    def update(self, **evidence):
        self.record["observation"].update(json_safe(evidence))

    def __exit__(self, error_type, error, traceback):
        self.record.update(finished_at=utc_now(), duration_ms=(time.perf_counter() - self.timer) * 1000,
                           status="error" if error else "ok")
        if error:
            self.record["error"] = f"{error_type.__name__}: {error}"
        self.record["observation"]["trace"] = self.record["spans"]
        _current_span.reset(self.span_token)
        _current_trace.reset(self.token)
        try:
            self.receipt = record_trace(self.record, self.store, self.policy, self.root)
        except Exception as exc:
            # Monitoring must not replace an application result or mask its exception.
            self.receipt = None
            warnings.warn(f"Evals trace could not be persisted: {exc}", RuntimeWarning, stacklevel=2)
        return False


class span:
    def __init__(self, name, *, kind="custom", input=None):
        self.owner = _current_trace.get()
        self.record = {"id": uuid.uuid4().hex, "parent_id": _current_span.get(),
                       "name": name, "kind": kind, "input": json_safe(input)}

    def __enter__(self):
        if self.owner is None:
            raise ValueError("A span must be inside an Evals trace")
        self.record["started_at"] = utc_now()
        self.timer = time.perf_counter()
        self.token = _current_span.set(self.record["id"])
        self.owner.record["spans"].append(self.record)
        self.tool_record = None
        if self.record["kind"] == "tool":
            self.tool_record = {"name": self.record["name"], "arguments": self.record["input"]}
            self.owner.record["observation"].setdefault("tools", []).append(self.tool_record)
        return self

    def set_output(self, output):
        self.record["output"] = json_safe(output)

    def __exit__(self, error_type, error, traceback):
        self.record.update(finished_at=utc_now(), duration_ms=(time.perf_counter() - self.timer) * 1000,
                           status="error" if error else "ok")
        if error:
            self.record["error"] = f"{error_type.__name__}: {error}"
        if self.tool_record is not None:
            self.tool_record.update(result=self.record.get("output"), status=self.record["status"])
        _current_span.reset(self.token)
        return False


def observe(function=None, *, kind="custom", name=None, store=None):
    """Decorate sync/async components. The outermost observed call creates a trace."""
    def decorate(fn):
        label = name or fn.__name__

        def arguments(args, kwargs):
            return json_safe(dict(inspect.signature(fn).bind(*args, **kwargs).arguments))

        def finish(owner, value):
            if owner is not None:
                if isinstance(value, dict):
                    owner.update(**value)
                elif isinstance(value, str):
                    owner.update(output=value)

        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapper(*args, **kwargs):
                if _current_trace.get() is None:
                    with trace(label, input=arguments(args, kwargs), store=store) as owner:
                        with span(label, kind=kind, input=arguments(args, kwargs)) as current:
                            value = await fn(*args, **kwargs)
                            current.set_output(value)
                            finish(owner, value)
                            return value
                with span(label, kind=kind, input=arguments(args, kwargs)) as current:
                    value = await fn(*args, **kwargs)
                    current.set_output(value)
                    return value
            return async_wrapper

        @wraps(fn)
        def wrapper(*args, **kwargs):
            if _current_trace.get() is None:
                with trace(label, input=arguments(args, kwargs), store=store) as owner:
                    with span(label, kind=kind, input=arguments(args, kwargs)) as current:
                        value = fn(*args, **kwargs)
                        current.set_output(value)
                        finish(owner, value)
                        return value
            with span(label, kind=kind, input=arguments(args, kwargs)) as current:
                value = fn(*args, **kwargs)
                current.set_output(value)
                return value
        return wrapper
    return decorate(function) if function is not None else decorate
