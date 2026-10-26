#!/usr/bin/env python3
"""Hook PreToolUse (Bash) — sortie de pytest courte et entière.

Refuse une commande pytest sans `--tb=line`, `--tb=short` ou `--tb=no` : les tracebacks complets noient le résumé. Refuse aussi une sortie de pytest coupée par `head`, `tail` ou `grep` : la liste des échecs arrive tronquée, et il faut relancer la suite pour la lire.

Mécanisme : deny + motif, comme les autres hooks Bash du projet.
"""

from __future__ import annotations

import json
import re
import sys

from memory_guard import strip_heredocs, strip_quotes

PYTEST = re.compile(r"(?:^|[\s;&|(/])pytest(?=[\s;&|)]|$)")
SHORT_TRACEBACK = re.compile(r"--tb[= ](?:line|short|no)\b")
TRUNCATED = re.compile(r"\|\s*(?:head|tail|grep)\b")


def refusal(command: str) -> str | None:
    """Motif du refus, ou `None` si la commande lance pytest comme il faut (ou ne le lance pas)."""
    text = strip_quotes(strip_heredocs(command))
    match = PYTEST.search(text)
    if match is None:
        return None
    if not SHORT_TRACEBACK.search(text):
        return (
            "pytest sans `--tb=line` : les tracebacks complets noient le résumé. Lance par exemple :\n"
            "  .venv/Scripts/python -m pytest <chemins> --tb=line -p no:cacheprovider\n"
            "Pour le détail d'un échec, relance ce seul test avec `--tb=short`."
        )
    if TRUNCATED.search(text, match.end()):
        return (
            "Sortie de pytest coupée par head, tail ou grep : la liste des échecs arriverait "
            "tronquée. Avec `--tb=line`, la sortie entière tient en quelques dizaines de lignes."
        )
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return 0
    reason = refusal(payload.get("tool_input", {}).get("command", ""))
    if reason is None:
        return 0
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
