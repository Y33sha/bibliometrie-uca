#!/usr/bin/env python3
"""Hook PreToolUse (Bash) — garde-fous sur les commandes shell de Claude Code.

Règle 1 : `cd` en commande composée. Toléré uniquement en tête de chaîne, et vers une cible qui reste dans le projet — sa racine comprise, en chemin absolu comme relatif.

Règle 2 : contournement des hooks git (`--no-verify` & co), au commit comme au push. Le pre-commit et le pre-push font partie du contrat du dépôt.

Règle 3 : indexation globale (`git add .`, `-A`, `-u`, `git commit -a`). Elle embarque les modifications d'autrui — l'utilisateur, ou un autre agent — présentes dans l'arbre de travail.

Installation : .claude/settings.json

{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command",
            "command": "python \"$CLAUDE_PROJECT_DIR/.claude/hooks/commit_guard.py\"",
            "timeout": 10 }
        ]
      }
    ]
  }
}
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# --- Découpage ------------------------------------------------------------

SPLIT_RE = re.compile(r"&&|\|\||(?<!\|)\|(?!\|)|;|\n")
LEADING_RE = re.compile(r"^\s*(?:\w+=\S*\s+)*")

# --- Règle 1 : cd ---------------------------------------------------------

# Le hook lit le texte de la commande, pas son expansion par le shell : une cible qui porte `~`, `$VAR` ou un glob n'est pas résoluble ici, donc pas vérifiable.
UNRESOLVABLE_CD_TARGET = re.compile(r"[$~*?`]")

# --- Règle 2 : contournement des hooks git --------------------------------

BYPASS_RE = re.compile(r"--no-verify|--no-gpg-sign|HUSKY=0|SKIP=|PRE_COMMIT_ALLOW")

# --- Règle 3 : indexation globale -----------------------------------------

PROMISCUOUS_RE = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)*add\s+(?:-A\b|--all\b|-u\b|--update\b|\.(?=\s|$)|\*(?=\s|$))"
    r"|\bgit\s+commit\b(?=[^\n]*\s-(?:a\b|[a-zA-Z]*a[a-zA-Z]*\b))"
    r"|\bgit\s+stash\b(?!\s+list\b)"
    r"|\bgit\s+checkout\s+--\s+\.(?=\s|$)"
    r"|\bgit\s+reset\s+--hard\b"
)


def strip_heredocs(cmd: str) -> str:
    """Neutralise le corps des heredocs : ce n'est pas du shell."""
    out = cmd
    for m in re.finditer(r"<<-?\s*(['\"]?)(\w+)\1", cmd):
        delim = re.escape(m.group(2))
        body = re.compile(
            r"(<<-?\s*['\"]?" + delim + r"['\"]?)(.*?)(^\s*" + delim + r"\s*$)",
            re.DOTALL | re.MULTILINE,
        )
        out = body.sub(r"\1 <HEREDOC>", out)
    return out


def segments(cmd: str) -> list[str]:
    return [s.strip() for s in SPLIT_RE.split(cmd) if s.strip()]


def parts(segment: str) -> list[str]:
    return LEADING_RE.sub("", segment).split()


def cd_target(segment: str) -> str | None:
    p = parts(segment)
    if not p or p[0] != "cd":
        return None
    return p[1].strip("\"'") if len(p) > 1 else "~"


def decide(decision: str, reason: str) -> int:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": decision,
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    return 0


def check_cd(segs: list[str]) -> int | None:
    if len(segs) < 2:
        return None
    root_env = os.environ.get("CLAUDE_PROJECT_DIR")
    if not root_env:
        return None
    root = Path(root_env).resolve()
    for i, seg in enumerate(segs):
        target = cd_target(seg)
        if target is None:
            continue
        if i != 0:
            return decide(
                "deny",
                "Commande refusée : `cd` au milieu d'une chaîne. Un changement de "
                "répertoire n'est toléré qu'en tête de commande composée.",
            )
        if UNRESOLVABLE_CD_TARGET.search(target):
            return decide(
                "deny",
                f"Commande refusée : `cd {target}`. La cible porte une expansion shell "
                "(`~`, `$VAR`, glob) : ce garde-fou lit le texte de la commande, il ne "
                "peut pas vérifier où elle mène. Écris le chemin littéralement.",
            )
        # Résolution depuis la racine : pathlib absorbe une cible absolue, greffe une cible relative, et évalue les `..`.
        dest = (root / target).resolve()
        if dest != root and root not in dest.parents:
            return decide(
                "deny",
                f"Commande refusée : `cd {target}` mène hors du projet ({dest}).\n"
                "Vise un répertoire du projet, ou utilise les options prévues pour "
                "viser ailleurs : `git -C <dir>`, `npm --prefix <dir>`.",
            )
    return None


def check_bypass(cmd: str) -> int | None:
    if not BYPASS_RE.search(cmd):
        return None
    return decide(
        "deny",
        "Commande refusée : contournement des hooks git (`--no-verify` ou "
        "équivalent), au commit comme au push. Le pre-commit ne modifie aucun "
        "fichier ; le pre-push exécute les tests. Les deux font partie du contrat "
        "du dépôt et ne se désactivent pas.\n"
        "S'ils échouent, l'échec est le résultat : corrige la cause, ou remonte-la. "
        "Ne rejoue pas la commande avec un contournement, et ne propose pas de le "
        "faire.",
    )


def check_promiscuous(cmd: str) -> int | None:
    if not PROMISCUOUS_RE.search(cmd):
        return None
    return decide(
        "deny",
        "Commande refusée : opération indiscriminée sur l'arbre de travail "
        "(`git add .` / `-A` / `-u`, `git commit -a`, `git stash`, "
        "`git reset --hard`, `git checkout -- .`).\n"
        "L'arbre de travail contient des modifications qui ne sont pas les tiennes : "
        "celles de l'utilisatrice, ou celles d'une autre session. Tu n'as le droit "
        "de toucher qu'aux fichiers que tu as toi-même modifiés.\n"
        "Indexe-les explicitement, chemin par chemin : "
        "`git add chemin/vers/fichier.py autre/fichier.ts`.",
    )


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

    for result in (
        check_cd(segs),
        check_bypass(cmd),
        check_promiscuous(cmd),
    ):
        if result is not None:
            return result

    return 0


if __name__ == "__main__":
    sys.exit(main())
