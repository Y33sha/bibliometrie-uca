#!/usr/bin/env python3
"""Hook PreToolUse (Bash) — vitest lancé depuis le dossier du frontend.

Refuse une commande qui appelle vitest directement (`npx vitest`, `npm exec -- vitest`…) : vitest prend le répertoire courant pour racine, ramasse depuis la racine du dépôt les copies de `mutants/` et y génère un `.svelte-kit/`. `npm --prefix interfaces/frontend run test` se place dans le dossier du paquet, quel que soit le répertoire courant.

Mécanisme : deny + motif, comme les autres hooks Bash du projet.
"""

from __future__ import annotations

import json
import re
import sys

from memory_guard import PREFIX, strip_heredocs, strip_quotes

VITEST = re.compile(r"(?:^|[\s;&|(/])vitest(?=[\s;&|)]|$)")


def refusal(command: str) -> str | None:
    """Motif du refus, ou `None` si la commande n'appelle pas vitest directement."""
    if VITEST.search(strip_quotes(strip_heredocs(command))) is None:
        return None
    return (
        "vitest appelé directement : il tourne alors depuis le répertoire courant. Lance plutôt :\n"
        f'  {PREFIX} npm --prefix "$CLAUDE_PROJECT_DIR/interfaces/frontend" run test -- <chemin relatif au frontend>'
    )


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
