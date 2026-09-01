"""
Ratchet: no NEW direct AI client constructions outside ai_governance/.

WHY
---
`ai_governance/` exists to centralise model calls, the daily-usage limit and
cost attribution. A module that constructs `anthropic.Anthropic(...)` or
`openai.OpenAI(...)` itself is invisible to all three — which is why cost was
unattributable, why a model deprecation meant grepping the whole tree, and why
the "Gemini is disabled in scheduled jobs" policy was enforced by a comment
rather than by anything (TOR-22).

WHY A RATCHET AND NOT A HARD BAN
--------------------------------
Four live modules still construct clients directly. They use the Anthropic
Messages API shape (`client.messages.create`) while the gateway speaks the
OpenAI-compatible Bedrock endpoint, so migrating them means rewriting their
request AND response parsing — not a mechanical change, and not one to make
without exercising it against the real API.

So they are listed as a known baseline. The check fails on anything NOT in that
list, which stops the problem growing while the four are migrated properly. As
each one moves, delete its line from BASELINE. The list only ever shrinks.

If your use case is not covered by a typed gateway method, call
`get_ai_gateway().complete(prompt)` — that is what it is for. Do not add a
baseline entry to get around this check.

USAGE
    python backend/scripts/check_ai_gateway.py
"""

import ast
import io
import os
import sys

# Known, accepted violations. NEVER add to this list — only remove.
BASELINE = {
    "email_classification/reply_intent.py",
    "email_classification/reply_sentiment.py",
    "email_crm_pipeline/email_classifier.py",
    "email_crm_pipeline/email_drafter.py",
}

# Directories exempt by nature: dead code kept for history, and one-off
# operator scripts that run outside the app and exit.
EXEMPT_PREFIXES = ("deprecated/", "scripts/", "tests/")

CLIENT_CONSTRUCTORS = {
    "openai.OpenAI", "OpenAI", "openai.AsyncOpenAI", "AsyncOpenAI",
    "anthropic.Anthropic", "Anthropic",
    "anthropic.AsyncAnthropic", "AsyncAnthropic",
    "genai.GenerativeModel", "GenerativeModel",
}

SKIP_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    os.chdir(root)

    found = {}
    for dirpath, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.endswith(".py"):
                continue
            rel = os.path.join(dirpath, f).replace(os.sep, "/")[2:]
            if rel.startswith("ai_governance/") or rel.startswith(EXEMPT_PREFIXES):
                continue
            try:
                tree = ast.parse(io.open(rel, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and \
                        ast.unparse(node.func) in CLIENT_CONSTRUCTORS:
                    found.setdefault(rel, []).append(node.lineno)

    new = {p: lines for p, lines in found.items() if p not in BASELINE}
    fixed = BASELINE - set(found)

    if fixed:
        print("These baseline entries no longer construct a client — remove "
              "them from BASELINE in this script:")
        for p in sorted(fixed):
            print(f"  {p}")
        print()

    if new:
        print(f"{len(new)} module(s) construct an AI client directly:\n")
        for p, lines in sorted(new.items()):
            print(f"  {p}:{','.join(str(n) for n in lines)}")
        print(
            "\nRoute the call through ai_governance instead:\n"
            "    from ai_governance.ai_gateway import get_ai_gateway\n"
            "    text = get_ai_gateway().complete(prompt)\n"
            "\nA directly-constructed client bypasses the daily limit and the "
            "usage counters, so its cost is unattributable and its model is "
            "invisible to a deprecation sweep."
        )
        return 1

    print(f"no new direct AI clients ({len(BASELINE & set(found))} known "
          f"baseline violations remain)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
