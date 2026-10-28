"""Layer 1: a static allow-list over the code a model wrote, before anything runs it.

The controller is one class, `GeneratedArenaSkill`, with `compute_action(self, obs)`. It may import only `math`, `numpy`, `typing` and `dataclasses`; it may not open files, reach the
network or the operating system, use reflection (`getattr`, `eval`, dunder attributes), loop without a bound (`while`), or be larger than `MAX_NODES` syntax nodes. Anything else is refused
with a plain reason that is handed back to the model for one retry.
"""
from __future__ import annotations

import ast

ALLOWED_MODULES = frozenset({"math", "numpy", "typing", "dataclasses"})
BANNED_NAMES = frozenset({"eval", "exec", "compile", "open", "input", "getattr", "setattr", "delattr", "globals", "locals", "vars", "dir", "__import__", "breakpoint", "help",
                          "exit", "quit", "memoryview", "super", "type", "object", "classmethod", "staticmethod", "property", "print"})
BANNED_ATTRS = frozenset({"system", "popen", "environ", "getenv", "load", "loads", "dump", "dumps", "read", "write", "open", "save", "savetxt", "fromfile", "tofile", "ctypeslib",
                          "f2py", "testing", "distutils", "lib", "ctypes", "core", "__class__"})
MAX_NODES = 800
REQUIRED_CLASS = "GeneratedArenaSkill"
REQUIRED_METHOD = "compute_action"


class SkillRejected(Exception):
    """The code was refused; the message says why in words a model can act on."""


class _Gate(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes = 0

    def visit(self, node: ast.AST):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise SkillRejected(f"the skill is too large (more than {MAX_NODES} syntax nodes): make it smaller")
        return super().visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] not in ALLOWED_MODULES:
                raise SkillRejected(f"import of '{alias.name}' is not allowed; only {sorted(ALLOWED_MODULES)} may be imported")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level or not node.module or node.module.split(".")[0] not in ALLOWED_MODULES:
            raise SkillRejected(f"import from '{node.module}' is not allowed; only {sorted(ALLOWED_MODULES)} may be imported")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("__") or node.attr.endswith("__") or node.attr in BANNED_ATTRS:
            raise SkillRejected(f"attribute '{node.attr}' is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id.startswith("__") or node.id in BANNED_NAMES:
            raise SkillRejected(f"the name '{node.id}' is not allowed")
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        raise SkillRejected("'while' loops are not allowed in a 60 Hz skill: use a bounded 'for' over a range")

    def visit_Global(self, node: ast.Global):
        raise SkillRejected("'global' is not allowed: keep state on self")

    def visit_Nonlocal(self, node: ast.Nonlocal):
        raise SkillRejected("'nonlocal' is not allowed")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        raise SkillRejected("async code is not allowed")

    def visit_Await(self, node: ast.Await):
        raise SkillRejected("await is not allowed")

    def visit_Yield(self, node: ast.Yield):
        raise SkillRejected("generators are not allowed")

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, (int, float)) and abs(node.value) > 10 ** 9:
            raise SkillRejected("numbers larger than a billion are not allowed")
        if isinstance(node.value, str) and len(node.value) > 200:
            raise SkillRejected("strings longer than 200 characters are not allowed")
        self.generic_visit(node)


def check(code: str) -> tuple[bool, str]:
    """(True, "ok") when the code passes the gate, else (False, why)."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as error:
        return False, f"syntax error at line {error.lineno}: {error.msg}"
    try:
        _Gate().visit(tree)
    except SkillRejected as error:
        return False, str(error)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == REQUIRED_CLASS]
    if not classes:
        return False, f"the code must define 'class {REQUIRED_CLASS}'"
    methods = {n.name for n in classes[0].body if isinstance(n, ast.FunctionDef)}
    if REQUIRED_METHOD not in methods:
        return False, f"'{REQUIRED_CLASS}' must implement '{REQUIRED_METHOD}(self, obs)'"
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef, ast.Assign, ast.AnnAssign, ast.Expr)):
            return False, f"only imports, classes, functions and simple constants may appear at the top level (found {type(node).__name__})"
        if isinstance(node, ast.Expr) and not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            return False, "no code may run at import time; only a docstring may stand alone at the top level"
    return True, "ok"
