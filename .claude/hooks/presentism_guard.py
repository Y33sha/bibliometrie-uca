#!/usr/bin/env python3
"""Hook PreToolUse : bloque les écritures dont les docstrings/commentaires *ajoutés* décrivent le passé, justifient un choix, ou instruisent le lecteur, au lieu de décrire l'état présent du code.

Installation (settings.json, projet ou ~/.claude) :

{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          { "type": "command",
            "command": "python $CLAUDE_PROJECT_DIR/.claude/hooks/presentism_guard.py",
            "timeout": 15 }
        ]
      }
    ]
  }
}

Contrat : exit 2 = l'écriture est refusée, stderr est renvoyé au modèle.
Exit 0 = laisse passer. (Exit 1 ne bloque RIEN dans Claude Code.)
"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

# --- Lexique ---------------------------------------------------------------
# HARD : marqueurs diachroniques / justificatifs. Aucun usage légitime dans une docstring qui se borne à décrire l'état présent. -> blocage sec.
HARD = [
    r"désormais",
    r"dorénavant",
    r"auparavant",
    r"précédemment",
    r"anciennement",
    r"historiquement",
    r"jusqu'?(?:ici|à présent|alors)",
    r"n['e]\s*(?:\w+\s+)?plus\b",
    r"n['e]\s*(?:\w+\s+)?jamais\b",
    r"au lieu de",
    r"plutôt que",
    r"contrairement",
    r"remplace(?:nt|ment)?\b",
    r"nouveau|nouvelle|nouveaux|nouvelles",
    r"ancien(?:ne|s|nes)?\b",
    r"legacy",
    r"deprecated|obsolète",
    r"(?:c'est|il s'agit) pourquoi",
    r"\bcar\b|\bpuisque\b|\bdonc\b|\bainsi\b",  # justification
]

# SOFT : peuvent être légitimes (contrat d'appel réel : « ne pas appeler depuis un thread »). Ne bloquent que si la docstring est déjà longue -> voir plus bas.
SOFT = [
    r"ne (?:doit|doivent|faut) pas",
    r"ne pas\b",
    r"n['e]\s*(?:\w+\s+)?pas à\b",
    r"\bdo not\b|\bdon't\b|\bmust not\b",
]

HARD_RE = re.compile("|".join(HARD), re.IGNORECASE)
SOFT_RE = re.compile("|".join(SOFT), re.IGNORECASE)

# Seuils de longueur. Un commentaire au-delà de `MAX_COMMENT_CHARS` bloque : la concision est son contrat.
# Pour une docstring, la longueur n'active que l'examen SOFT, elle ne bloque pas seule (un mécanisme se décrit parfois sur plusieurs paragraphes).
MAX_DOCSTRING_CHARS = 1500
MAX_DOCSTRING_LINES = 20
MAX_COMMENT_CHARS = 250

RULE = """RÈGLE DE RÉDACTION (non négociable) — docstrings et commentaires :

Une docstring décrit CE QUE FAIT le code, au présent, pour quelqu'un qui n'a jamais vu la version précédente. Elle ne contient JAMAIS :
  - ce qui existait avant, ce qui a changé, ce qui a été remplacé ;
  - la justification d'un choix de conception ("car", "au lieu de", "ce ne sont pas des X mais des Y", "elles n'ont donc pas à ...") ;
  - une mise en garde adressée au futur mainteneur ;
  - le mot "désormais", "nouveau", "ancien", "ne ... plus".

Le raisonnement qui a mené au code va dans le message de commit ou dans une ADR — pas dans le fichier source.

Réécris la docstring en une à trois phrases descriptives au présent, puis recommence l'écriture. Ne demande pas confirmation.
"""


def read_original(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def project_new_content(tool: str, ti: dict, original: str) -> str | None:
    """Reconstruit le contenu du fichier tel qu'il serait après l'écriture."""
    if tool == "Write":
        return ti.get("content", "")
    if tool == "Edit":
        old, new = ti.get("old_string", ""), ti.get("new_string", "")
        if old and old in original:
            count = -1 if ti.get("replace_all") else 1
            return original.replace(old, new, count)
        return new  # fragment seul : on l'analysera en dégradé
    if tool == "MultiEdit":
        cur = original
        for e in ti.get("edits", []):
            cur = cur.replace(e.get("old_string", ""), e.get("new_string", ""), 1)
        return cur
    return None


def extract_prose(source: str) -> tuple[list[str], list[str]]:
    """(docstrings, commentaires) d'un source Python. Tolère un source partiel."""
    docstrings: list[str] = []
    comments: list[str] = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                d = ast.get_docstring(node, clean=False)
                if d:
                    docstrings.append(d)
    except SyntaxError:
        # Fragment non parsable : on récupère les blocs triple-quote bruts.
        docstrings = re.findall(r'"""(.*?)"""', source, re.DOTALL)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                comments.append(tok.string.lstrip("# ").strip())
    except (tokenize.TokenError, IndentationError, SyntaxError):
        comments += [
            m.group(1).strip()
            for m in re.finditer(r"^\s*#\s?(.*)$", source, re.MULTILINE)
        ]
    return docstrings, comments


def violations(text: str, kind: str) -> list[str]:
    out: list[str] = []
    n_lines = text.count("\n") + 1
    too_long = (
        len(text) > MAX_DOCSTRING_CHARS or n_lines > MAX_DOCSTRING_LINES
        if kind == "docstring"
        else len(text) > MAX_COMMENT_CHARS
    )

    for m in HARD_RE.finditer(text):
        out.append(f'marqueur diachronique/justificatif : "{m.group(0)}"')
    if too_long and kind == "comment":
        out.append(
            f"commentaire trop long ({len(text)} car.) : "
            "une description d'état présent tient sur une ligne"
        )
    if too_long or HARD_RE.search(text):
        for m in SOFT_RE.finditer(text):
            out.append(f'formulation prescriptive/négative : "{m.group(0)}"')
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input", {}) or {}
    path = ti.get("file_path", "")
    if tool not in {"Write", "Edit", "MultiEdit"} or not path.endswith(".py"):
        return 0

    original = read_original(path)
    new_content = project_new_content(tool, ti, original)
    if new_content is None:
        return 0

    old_doc, old_com = extract_prose(original)
    new_doc, new_com = extract_prose(new_content)

    # On n'audite QUE la prose ajoutée : le legacy n'est pas rejugé à chaque edit.
    added = [("docstring", d) for d in new_doc if d not in old_doc]
    added += [("commentaire", c) for c in new_com if c not in old_com]

    findings: list[str] = []
    for kind, text in added:
        for v in violations(text, "docstring" if kind == "docstring" else "comment"):
            head = " ".join(text.split())[:70]
            findings.append(f"  - [{kind}] « {head}… » → {v}")

    if not findings:
        return 0

    print(
        "ÉCRITURE REFUSÉE — la prose ajoutée ne décrit pas l'état présent du code.\n\n"
        + "\n".join(findings)
        + "\n\n"
        + RULE,
        file=sys.stderr,
    )
    return 2  # 2 = blocage. Surtout pas 1.


if __name__ == "__main__":
    sys.exit(main())
