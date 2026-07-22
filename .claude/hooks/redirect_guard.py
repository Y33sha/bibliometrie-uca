#!/usr/bin/env python3
"""Hook PreToolUse (Bash) — redirige vers les outils natifs.

Ne bloque QUE les commandes shell qui ont un équivalent natif direct, et seulement dans leur forme autonome (pas de pipe, pas de redirection glue). But : éviter que Claude relise/réécrive/cherche « à la main » et te sollicite pour des opérations qu'un outil natif fait sans autorisation.

Ce hook ne prétend PAS prédire ce qui déclenchera un prompt (le hook ne connaît pas ta liste de permissions). Il ne fait qu'une chose : rediriger un petit ensemble d'anti-patterns vers Read / Write / Edit / Grep / Glob.

Limite connue et assumée : un script Python arbitraire qui lit/écrit des fichiers n'est pas détectable. Seules les formes inline (`python -c "..."`) le sont.

Mécanisme : deny + motif. La réécriture transparente (updatedInput) est documentée mais instable en PreToolUse multi-hooks — non utilisée ici.

Installe-le en SECOND hook Bash, à côté de bash_guard.py. Désactivable indépendamment si les faux positifs te gênent : c'est de l'ergonomie, pas de la sécurité.
"""

from __future__ import annotations

import json
import re
import sys

SPLIT_RE = re.compile(r"&&|\|\||(?<!\|)\|(?!\|)|;|\n")
LEADING_RE = re.compile(r"^\s*(?:\w+=\S*\s+)*")

# Écriture : on ne vise QUE les fichiers de code — pas .txt/.json/.md/.log, qui sont des cibles de capture de sortie légitimes (`pytest > report.txt`).
SRC_CODE = r"\.(?:py|ts|tsx|js|jsx|svelte|vue|rs|go|java|rb|php|sql|sh|css|scss|html)(?![A-Za-z])"

READ_CMDS = {"cat", "head", "tail", "nl", "bat"}
# Cluster de flags courts contenant r/R (‑r, ‑rn, ‑Rni), en excluant les longues options (‑‑regexp) via (?!-).
SEARCH_RECURSIVE = re.compile(r"\b[ef]?grep\b[^|;&]*\s-(?!-)[a-zA-Z]*[rR]")
FIND_NAME = re.compile(r"\bfind\s+\S+.*\s-i?name\b")
AUTHOR_WRITE = re.compile(
    r"\b(?:echo|printf|cat)\b[^|;&]*?>\s*[^\s|;&<>]*"
    + SRC_CODE
    + r"|\btee\s+\S*"
    + SRC_CODE
    + r"|\bpython3?\s+-c\b[^\n]*(?:open\([^)]*['\"][wa]['\"]|\.write\()"
    + r"|\bsed\s+-i\b"
)


def strip_heredocs(cmd: str) -> str:
    out = cmd
    for m in re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", cmd):
        delim = re.escape(m.group(2))
        out = re.compile(
            r"(<<-?\s*['\"]?" + delim + r"['\"]?)(.*?)(^\s*" + delim + r"\s*$)",
            re.DOTALL | re.MULTILINE,
        ).sub(r"\1 <HEREDOC>", out)
    return out


def segments(cmd: str) -> list[str]:
    return [s.strip() for s in SPLIT_RE.split(cmd) if s.strip()]


def parts(seg: str) -> list[str]:
    return LEADING_RE.sub("", seg).split()


def has_pipe(cmd: str) -> bool:
    return bool(re.search(r"(?<!\|)\|(?!\|)", cmd))


def decide(reason: str) -> int:
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


def check_read(cmd: str, segs: list[str]) -> int | None:
    # Uniquement une lecture AUTONOME : un seul segment, pas de pipe, pas de redirection. `cat f | grep x` ou `cat f > out` sont de la glue -> on laisse.
    if len(segs) != 1 or has_pipe(cmd) or re.search(r"[<>]", cmd):
        return None
    p = parts(segs[0])
    if not p or p[0] not in READ_CMDS:
        return None
    args = [a for a in p[1:] if not a.startswith("-")]
    if not args or args == ["-"]:
        return None  # lecture de stdin, pas d'un fichier
    return decide(
        f"Commande refusée : `{p[0]}` pour lire un fichier. Utilise l'outil Read, "
        "qui lit sans solliciter d'autorisation et te donne la numérotation de "
        "lignes attendue par Edit. Réserve `cat`/`head`/`tail` aux pipelines "
        "(quand la sortie alimente une autre commande)."
    )


def check_write(cmd: str) -> int | None:
    if not AUTHOR_WRITE.search(cmd):
        return None
    return decide(
        "Commande refusée : rédaction d'un fichier source via le shell "
        "(`echo >`, heredoc, `tee`, `sed -i`, `python -c ...write`). Utilise Write "
        "pour créer un fichier, Edit pour en modifier un. Ces outils passent par "
        "la même validation que le reste et évitent les états d'écriture partielle."
    )


def check_search(cmd: str) -> int | None:
    if SEARCH_RECURSIVE.search(cmd):
        return decide(
            "Commande refusée : `grep -r`. Utilise l'outil Grep (ripgrep), plus "
            "rapide et sans autorisation. Garde `grep` pour filtrer la sortie d'un "
            "pipe, pas pour parcourir l'arborescence."
        )
    if FIND_NAME.search(cmd):
        return decide(
            "Commande refusée : `find -name`. Utilise l'outil Glob pour lister des "
            "fichiers par motif de nom."
        )
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    raw = (payload.get("tool_input") or {}).get("command", "")
    if not raw.strip():
        return 0

    cmd = strip_heredocs(raw)
    segs = segments(cmd)

    for r in (check_write(raw), check_read(cmd, segs), check_search(cmd)):
        if r is not None:
            return r
    return 0


if __name__ == "__main__":
    sys.exit(main())
