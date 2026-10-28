#!/usr/bin/env python3
"""Hook PreToolUse (Bash) — plafonne la mémoire des calculs lancés par Claude.

Refuse toute commande qui lance Python, pytest, Node ou npm hors d'un scope systemd plafonné. La commande commence par le préfixe `PREFIX`, qui borne la mémoire du processus et de ses enfants et interdit le swap : un calcul qui dépasse le plafond est tué, et la machine reste utilisable.

Mécanisme : deny + motif, comme les autres hooks Bash du projet.
"""

from __future__ import annotations

import json
import re
import sys

PREFIX = "systemd-run --user --scope --quiet -p MemoryMax=2G -p MemorySwapMax=0"

# Programmes dont la mémoire est plafonnée : interpréteurs et lanceurs de tests ou de builds.
HEAVY = re.compile(
    r"(?:^|[\s;&|(/])(?:python3?(?:\.\d+)?|pytest|alembic|node|npm|npx|vitest|svelte-kit|uv\s+run)(?=[\s;&|)]|$)"
)
CAPPED = re.compile(r"^\s*systemd-run\s+--user\s+--scope\b[^\n]*\bMemoryMax=")


def strip_heredocs(cmd: str) -> str:
    """Retire le corps des heredocs : leur texte n'est pas une commande."""
    out = cmd
    for m in re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", cmd):
        delim = re.escape(m.group(2))
        out = re.compile(
            r"(<<-?\s*['\"]?" + delim + r"['\"]?)(.*?)(^\s*" + delim + r"\s*$)",
            re.DOTALL | re.MULTILINE,
        ).sub(r"\1", out)
    return out


def strip_quotes(cmd: str) -> str:
    """Retire le contenu des chaînes entre guillemets : un message de commit qui cite Python n'en lance pas."""
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", cmd)


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return 0
    command = payload.get("tool_input", {}).get("command", "")
    if not HEAVY.search(strip_quotes(strip_heredocs(command))) or CAPPED.search(command):
        return 0
    reason = (
        "Calcul non plafonné en mémoire. Préfixe la commande par :\n"
        f"  {PREFIX} <commande>\n"
        "Le processus est tué s'il dépasse 2 Go, sans swap ; la machine reste utilisable."
    )
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
