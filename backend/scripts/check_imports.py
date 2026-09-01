"""
Static check: every intra-project import resolves under the runtime convention.

WHY
---
The app runs as `uvicorn main:app` with backend/ as the working directory, so
`routers`, `database` and friends are TOP-LEVEL packages. Until 2026-09-01, 338
try/except blocks papered over that by trying a relative import first and
falling back to an absolute one — which meant a module could carry a genuinely
broken import for months and nobody would know, because the other branch
happened to work.

Collapsing those fallbacks (TOR-11) removed the paper, and this is what keeps
it off: an import that does not resolve fails the build instead of failing a
router mount at 3am. It is the static counterpart to the fail-fast mounts
(TOR-05) and catches the same class of bug earlier and faster.

It found `leads/clay_routes.py` importing five of its own siblings as if they
were top-level modules — invisible while a relative fallback existed.

USAGE
    python -m scripts.check_imports          # from backend/
    python backend/scripts/check_imports.py  # from the repo root

Exit 0 clean, 1 with a list of unresolvable imports.

Third-party packages that simply are not installed in this environment
(selenium, scipy, reportlab, ...) are reported separately and do NOT fail the
run — they are an environment fact, not a code defect.
"""

import ast
import importlib.util
import io
import os
import sys

SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}


def backend_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(here)          # backend/scripts -> backend


def top_level_names(root: str) -> set:
    """What is importable as a bare top-level name with backend/ as cwd."""
    names = set()
    for entry in os.listdir(root):
        path = os.path.join(root, entry)
        if entry.endswith(".py") and entry != "__init__.py":
            names.add(entry[:-3])
        elif os.path.isdir(path) and entry not in SKIP_DIRS:
            names.add(entry)
    return names


def main() -> int:
    root = backend_root()
    os.chdir(root)
    toplevel = top_level_names(root)

    broken, missing_third_party = [], set()

    for dirpath, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            rel = os.path.join(dirpath, f).replace(os.sep, "/")[2:]
            try:
                tree = ast.parse(io.open(rel, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue

            package_parts = rel.split("/")[:-1]
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level:
                    continue                      # relative imports resolve locally
                head = (node.module or "").split(".")[0]
                if not head or head in toplevel:
                    continue
                try:
                    if importlib.util.find_spec(head) is not None:
                        continue                  # stdlib or installed package
                except (ImportError, ValueError):
                    pass

                # Does it exist as a sibling inside this file's own package?
                suggestion = None
                as_path = (node.module or "").replace(".", "/")
                for i in range(len(package_parts), 0, -1):
                    candidate = "/".join(package_parts[:i] + [as_path])
                    if os.path.exists(candidate + ".py") or os.path.isdir(candidate):
                        suggestion = ".".join(package_parts[:i] + [node.module])
                        break

                if suggestion:
                    broken.append((rel, node.lineno, node.module, suggestion))
                else:
                    missing_third_party.add(head)

    if missing_third_party:
        print("not installed in this environment (not a failure): "
              + ", ".join(sorted(missing_third_party)))

    if broken:
        print(f"\n{len(broken)} import(s) will fail at runtime:\n")
        for rel, lineno, module, suggestion in broken:
            print(f"  {rel}:{lineno}")
            print(f"      from {module} import ...")
            print(f"      -> from {suggestion} import ...")
        print("\nThe app runs with backend/ as the working directory, so an "
              "intra-package sibling must be imported by its full path from "
              "there (e.g. `from leads.clay_models import ...`), not as a bare "
              "top-level name.")
        return 1

    print("all intra-project imports resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
