#!/usr/bin/env python3
"""Offline guard: no TYPE_CHECKING-only name may be used in a live annotation.

A real startup crash on Python 3.13:

  NameError: name 'Ui_Nugget' is not defined
    main_app -> src.gui.translator

``translator.py`` imported ``Ui_Nugget`` under ``if TYPE_CHECKING:`` and then
used it as a parameter annotation. On Python 3.14+ PEP 649 makes annotations
lazy, so it imports fine; on 3.13 (and 3.12, 3.11, ...) annotations are
evaluated when the ``def`` runs, so merely importing the module raised
NameError -- the app died before its window was built.

The dev virtualenv is 3.15, so running the test suite on 3.15 cannot see this
class of bug. This check is therefore static: it resolves the annotation
expressions itself and fails on any file that would break on an older
interpreter, so the crash cannot come back unnoticed.

Run: python tools/test_annotation_imports.py
"""
import ast
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, ROOT)

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def type_checking_names(tree):
    """Names bound only inside an `if TYPE_CHECKING:` block."""
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for alias in sub.names:
                        names.add((alias.asname or alias.name).split(".")[0])
    return names


def live_annotations(tree):
    """Yield (lineno, source) for every annotation evaluated at def time."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            candidates = (list(args.posonlyargs) + list(args.args)
                          + list(args.kwonlyargs) + [args.vararg, args.kwarg])
            for arg in candidates:
                if arg is not None and arg.annotation is not None:
                    yield arg.lineno, ast.unparse(arg.annotation)
            if node.returns is not None:
                yield node.returns.lineno, ast.unparse(node.returns)
        elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
            yield node.lineno, ast.unparse(node.annotation)


def has_lazy_annotations(tree):
    """True when `from __future__ import annotations` is active."""
    for node in tree.body:
        if (isinstance(node, ast.ImportFrom) and node.module == "__future__"
                and any(a.name == "annotations" for a in node.names)):
            return True
    return False


def used_names(expr):
    parsed = ast.parse(expr, mode="eval")
    return {n.id for n in ast.walk(parsed) if isinstance(n, ast.Name)}


def python_files():
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_no_type_checking_hazards():
    print("\nno TYPE_CHECKING-only name in a live annotation")
    hazards = []
    scanned = 0
    for path in python_files():
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError as e:
            hazards.append(f"{path}: unparseable ({e})")
            continue
        scanned += 1
        guarded = has_lazy_annotations(tree)
        tc_names = type_checking_names(tree)
        if not tc_names:
            continue
        for lineno, expr in live_annotations(tree):
            # a string annotation is never evaluated, so it is always safe
            if expr.startswith(('"', "'")):
                continue
            hit = used_names(expr) & tc_names
            if hit and not guarded:
                hazards.append(f"{os.path.relpath(path, ROOT)}:{lineno} {sorted(hit)}")
    check(f"scanned {scanned} source files", scanned > 50, f"{scanned}")
    check("no file crashes on Python < 3.14", not hazards, "; ".join(hazards))


def test_translator_regression():
    print("\nthe exact startup crash stays fixed")
    from src.gui.translator import Translator

    check("translator imports", Translator is not None)
    ann = Translator.fix_ui_for_rtl.__annotations__.get("ui")
    check("fix_ui_for_rtl's annotation is never evaluated at def time",
          isinstance(ann, str), f"{ann!r}")
    check("and it still names the UI type", ann == "Ui_Nugget", f"{ann!r}")

    # the name really is absent at runtime -- that is what used to raise
    import src.gui.translator as mod
    try:
        eval("Ui_Nugget", vars(mod))
        resolvable = True
    except NameError:
        resolvable = False
    check("Ui_Nugget is TYPE_CHECKING-only, so the annotation must stay lazy",
          not resolvable)


def main():
    test_no_type_checking_hazards()
    test_translator_regression()
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
