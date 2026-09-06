"""Refuse d'écrire dans un `.md` tant que le skill `doc-style` n'a pas été invoqué.

La règle « supprimer, pas reformuler » ne s'applique que si le skill est chargé au moment
d'écrire. Ce garde-fou le vérifie dans le transcript, depuis le dernier message de
l'utilisatrice : une invocation par tour d'instruction suffit, les éditions suivantes du même
tour passent.
"""

import json
import pathlib
import sys

CODE_REFUS = 2

# Le skill est injecté dans le transcript comme un ou plusieurs tours utilisateur. Ces marqueurs les distinguent d'un vrai message de l'utilisatrice, et valent eux-mêmes invocation.
MARQUEURS_SKILL = (
    "<command-name>doc-style",
    "Re-invocation of /doc-style",
    "skills/doc-style",
)


MESSAGE = """ÉCRITURE REFUSÉE — le skill `doc-style` n'a pas été invoqué pour cette correction.

Toute retouche de documentation passe par lui, y compris la correction d'une affirmation
démentie par le code : sa règle de réparation dit de supprimer d'abord, et de ne réécrire
que si le lecteur perd quelque chose d'utile.

Invoque `doc-style`, puis recommence l'écriture."""


def _texte(entree: dict) -> str:
    contenu = entree.get("message", {}).get("content")
    if isinstance(contenu, str):
        return contenu
    return "".join(
        bloc.get("text", "")
        for bloc in contenu or []
        if isinstance(bloc, dict) and bloc.get("type") == "text"
    )


def _porte_marqueur(entree: dict) -> bool:
    texte = _texte(entree).replace("\\", "/")
    return any(marqueur in texte for marqueur in MARQUEURS_SKILL)


def _entrees(chemin: str) -> list[dict]:
    try:
        lignes = pathlib.Path(chemin).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entrees = []
    for ligne in lignes:
        try:
            entrees.append(json.loads(ligne))
        except json.JSONDecodeError:
            continue
    return entrees


def _est_message_humain(entree: dict) -> bool:
    """Vrai pour un tour de l'utilisatrice, faux pour un retour d'outil ou un corps de skill."""
    if entree.get("type") != "user":
        return False
    contenu = entree.get("message", {}).get("content")
    if not isinstance(contenu, str) and any(
        isinstance(bloc, dict) and bloc.get("type") == "tool_result" for bloc in contenu or []
    ):
        return False
    return not _porte_marqueur(entree)


def _invoque_doc_style(entree: dict) -> bool:
    if _porte_marqueur(entree):
        return True
    contenu = entree.get("message", {}).get("content")
    if isinstance(contenu, str):
        return False
    return any(
        isinstance(bloc, dict)
        and bloc.get("type") == "tool_use"
        and bloc.get("name") == "Skill"
        and (bloc.get("input") or {}).get("skill") == "doc-style"
        for bloc in contenu or []
    )


data = json.load(sys.stdin)
payload = data.get("tool_input") or data.get("inputs") or {}
chemin = payload.get("file_path", "")

if not chemin or pathlib.Path(chemin).suffix != ".md":
    sys.exit(0)

# `.claude/` porte la configuration de l'outillage, pas la documentation du projet.
if ".claude" in pathlib.Path(chemin).parts:
    sys.exit(0)

entrees = _entrees(data.get("transcript_path", ""))
depuis = 0
for rang, entree in enumerate(entrees):
    if _est_message_humain(entree):
        depuis = rang

if any(_invoque_doc_style(e) for e in entrees[depuis:]):
    sys.exit(0)

print(MESSAGE, file=sys.stderr)
sys.exit(CODE_REFUS)
