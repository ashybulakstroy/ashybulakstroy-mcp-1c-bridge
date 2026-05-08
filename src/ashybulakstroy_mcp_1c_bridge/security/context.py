from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import replace
from typing import Iterator
from uuid import uuid4

from .models import RequestContext

_REQUEST_CONTEXT: ContextVar[RequestContext | None] = ContextVar("bridge_request_context", default=None)


def new_trace_id() -> str:
    return uuid4().hex


def get_request_context() -> RequestContext | None:
    return _REQUEST_CONTEXT.get()


def ensure_request_context(**kwargs: object) -> RequestContext:
    current = get_request_context()
    if current is None:
        return RequestContext(trace_id=str(kwargs.pop("trace_id", None) or new_trace_id()), **kwargs)
    updates = {key: value for key, value in kwargs.items() if value is not None}
    if not updates:
        return current
    return replace(current, **updates)


def set_request_context(ctx: RequestContext) -> Token[RequestContext | None]:
    return _REQUEST_CONTEXT.set(ctx)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _REQUEST_CONTEXT.reset(token)


def clear_request_context() -> None:
    _REQUEST_CONTEXT.set(None)


@contextmanager
def request_context(ctx: RequestContext) -> Iterator[RequestContext]:
    token = set_request_context(ctx)
    try:
        yield ctx
    finally:
        reset_request_context(token)
