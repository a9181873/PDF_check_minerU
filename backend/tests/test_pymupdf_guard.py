import ast
import threading
from pathlib import Path

import pytest

from config import Settings
from services.compare_job_runner import CompareJobRunner
from services.pymupdf_guard import pymupdf_guard, pymupdf_serialized

_PYMUPDF_OBJECT_METHODS = {
    "add_highlight_annot",
    "add_rect_annot",
    "draw_rect",
    "get_drawings",
    "get_image_info",
    "get_image_rects",
    "get_images",
    "get_pixmap",
    "get_text",
    "insert_text",
    "new_page",
}


def test_all_production_fitz_calls_are_inside_serialized_scope():
    services_dir = Path(__file__).resolve().parents[1] / "services"
    violations: list[str] = []

    for source_path in sorted(services_dir.glob("*.py")):
        if source_path.name == "pymupdf_guard.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        parents = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            is_fitz_attribute = (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "fitz"
            )
            is_pymupdf_method = (
                isinstance(node, ast.Attribute)
                and node.attr in _PYMUPDF_OBJECT_METHODS
            )
            if not (is_fitz_attribute or is_pymupdf_method):
                continue

            current = node
            guarded = False
            while current is not None:
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    guarded = guarded or any(
                        ast.unparse(decorator) == "pymupdf_serialized"
                        for decorator in current.decorator_list
                    )
                current = parents.get(current)
            if not guarded:
                violations.append(f"{source_path.name}:{node.lineno}")

    assert violations == []


def test_pymupdf_guard_is_reentrant_on_same_thread():
    calls: list[str] = []

    @pymupdf_serialized
    def inner():
        calls.append("inner")

    @pymupdf_serialized
    def outer():
        calls.append("outer")
        with pymupdf_guard():
            inner()

    outer()

    assert calls == ["outer", "inner"]


def test_pymupdf_guard_serializes_multiple_threads():
    first_entered = threading.Event()
    second_attempted = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    order: list[str] = []

    def first_worker():
        with pymupdf_guard():
            order.append("first_enter")
            first_entered.set()
            assert release_first.wait(timeout=2)
            order.append("first_exit")

    def second_worker():
        assert first_entered.wait(timeout=2)
        second_attempted.set()
        with pymupdf_guard():
            order.append("second_enter")
            second_entered.set()
            order.append("second_exit")

    first = threading.Thread(target=first_worker)
    second = threading.Thread(target=second_worker)
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    assert second_attempted.wait(timeout=2)

    assert not second_entered.wait(timeout=0.05)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert order == ["first_enter", "first_exit", "second_enter", "second_exit"]


@pytest.mark.parametrize("configured", [0, 1, 2, 8])
def test_compare_thread_concurrency_is_forced_to_one(tmp_path, configured):
    configured_settings = Settings(
        data_dir=tmp_path,
        jwt_secret="test-secret",
        compare_max_concurrency=configured,
    )

    assert configured_settings.compare_max_concurrency == 1


def test_compare_job_runner_defensively_forces_one_worker():
    runner = CompareJobRunner(max_workers=8, max_pending=0)
    try:
        assert runner._executor._max_workers == 1
    finally:
        runner.shutdown()
