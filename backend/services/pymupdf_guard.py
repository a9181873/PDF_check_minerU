"""Process-wide serialization for every in-process PyMuPDF operation.

PyMuPDF does not support concurrent use from multiple Python threads.  The API
server has both a comparison worker and FastAPI's synchronous endpoint
threadpool, so limiting the comparison executor alone is insufficient.  Every
production function that owns a ``fitz.Document``, ``fitz.Page`` or
``fitz.Pixmap`` must use this shared re-entrant guard for the object's complete
lifetime.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from threading import RLock
from typing import Callable, Iterator, ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")

_PYMUPDF_LOCK = RLock()


@contextmanager
def pymupdf_guard() -> Iterator[None]:
    """Serialize PyMuPDF work across all threads in this Python process."""
    with _PYMUPDF_LOCK:
        yield


def pymupdf_serialized(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Run a synchronous PyMuPDF-owning function under the shared guard."""

    @wraps(function)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with pymupdf_guard():
            return function(*args, **kwargs)

    return wrapped
