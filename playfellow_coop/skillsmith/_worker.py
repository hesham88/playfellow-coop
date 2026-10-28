"""The isolated worker: runs one generated skill, one observation per line. Standard library and numpy only; started with `python -I` and a scrubbed environment by sandbox.py.

Protocol (one JSON object per line): the parent sends {"code": "..."} once, and the worker answers {"ready": true} or {"error": "..."}; then for each {"obs": {...}} the worker answers
{"action": {...}} or {"error": "..."}. The generated code runs with a small allow-list of builtins and an import hook that only lets math, numpy, typing and dataclasses through.
"""
import builtins
import json
import sys

ALLOWED = {"math", "numpy", "typing", "dataclasses"}
SAFE = ["abs", "all", "any", "bool", "dict", "divmod", "enumerate", "float", "int", "isinstance", "len", "list", "map", "max", "min", "pow", "range", "reversed", "round", "set",
        "slice", "sorted", "str", "sum", "tuple", "zip", "True", "False", "None", "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError", "Exception",
        "ArithmeticError", "StopIteration", "__build_class__", "NotImplementedError", "AttributeError", "RuntimeError", "OverflowError", "FloatingPointError", "hash", "repr", "callable",
        "filter", "next", "iter", "format", "ord", "chr", "frozenset", "bytes", "bytearray", "complex"]
real_import = builtins.__import__
# The skill never gets the real numpy module: only this proxy, built from the same name list the static gate uses, so a file-touching function (memmap, loadtxt ...) is simply absent.
NUMPY_ALLOWED = ["array", "asarray", "zeros", "ones", "full", "arange", "linspace", "clip", "sqrt", "abs", "dot", "mean", "median", "std", "sum", "min", "max", "argmax", "argmin",
                 "argsort", "sort", "where", "sign", "floor", "ceil", "round", "exp", "log", "sin", "cos", "arctan2", "hypot", "minimum", "maximum", "cumsum", "diff",
                 "concatenate", "stack", "reshape", "transpose", "flatnonzero", "nonzero", "count_nonzero", "any", "all", "isnan", "isfinite", "unique", "bincount",
                 "float32", "float64", "int32", "int64", "uint8", "bool_", "pi", "inf", "nan", "ndarray"]
_proxy = None


def numpy_proxy():
    global _proxy
    if _proxy is None:
        import types
        import numpy
        _proxy = types.SimpleNamespace(**{n: getattr(numpy, n) for n in NUMPY_ALLOWED}, linalg=types.SimpleNamespace(norm=numpy.linalg.norm))
    return _proxy


def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED:
        raise ImportError("import of " + name + " is not allowed")
    if name.split(".")[0] == "numpy":
        if name != "numpy":
            raise ImportError("import numpy itself; its submodules are not importable")
        proxy = numpy_proxy()
        for item in fromlist or ():
            if not hasattr(proxy, item):
                raise ImportError("numpy." + item + " is not allowed")
        return proxy
    return real_import(name, globals, locals, fromlist, level)


def main():
    stdin, stdout = sys.stdin, sys.stdout
    safe = {name: getattr(builtins, name) for name in SAFE if hasattr(builtins, name)}
    safe["__import__"] = guarded_import
    instance = None
    for line in stdin:
        try:
            message = json.loads(line)
            if "code" in message:
                scope = {"__builtins__": safe, "__name__": "skill"}
                # exec is the whole point of this file: it runs ONLY here, in the isolated process (python -I, scrubbed environment, restricted builtins and imports),
                # and only code that already passed the static gate in the parent
                exec(compile(message["code"], "<skill>", "exec"), scope)
                instance = scope[message.get("class", "GeneratedArenaSkill")]()
                reply = {"ready": True}
            elif "obs" in message:
                action = instance.compute_action(message["obs"])
                reply = {"action": action}
            elif "call" in message:
                name = message["call"]
                if not isinstance(name, str) or name.startswith("_"):
                    raise ValueError("a public method name is needed")
                reply = {"result": getattr(instance, name)(*message.get("args", []))}
            else:
                reply = {"error": "unknown message"}
            out = json.dumps(reply)
        except BaseException as error:  # noqa: BLE001 - a failing skill must never take the worker's protocol down
            out = json.dumps({"error": type(error).__name__ + ": " + str(error)[:200]})
        stdout.write(out + "\n")
        stdout.flush()


main()
