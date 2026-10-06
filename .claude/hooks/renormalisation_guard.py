"""Rappelle le cycle extraction / normalisation / raw store quand Claude emploie le mot « renormaliser ».

Le rappel est ajouté au contexte de Claude, sans bloquer ni forcer de réponse :

- `UserPromptSubmit` : quand la réponse précédente de Claude emploie le mot.
- `PostToolUse` (`Write`, `Edit`, `MultiEdit`) : quand le texte écrit emploie le mot.
"""

import json
import pathlib
import re
import sys

# Le nom de ce script ne compte pas comme emploi du mot.
MOT = re.compile(r"renormalis(?!ation_guard)", re.IGNORECASE)

CYCLE = """Rappel du cycle :

- `extract` upsert les payloads des sources dans `staging`. Une ligne repasse à `processed = FALSE` seulement si son payload a changé (`raw_hash` distinct), ou quand `fetch_truncated` la complète.
- `normalize` traite seulement les lignes `processed = FALSE`. Avec `--raw-store`, `mark_done` archive le payload dans le raw store, puis vide `raw_data`.
- Une notice déjà normalisée ne repasse donc pas par `normalize` d'elle-même. Rejouer la normalisation d'un stock passe par `interfaces/cli/maintenance/rehydrate_staging_from_raw_store.py`.
- `--normalize-full` ne remet aucune notice en file : il force la synchronisation des signatures des seules notices traitées pendant ce passage, même à bloc auteurs inchangé."""

RAPPEL_REPONSE = f"""Ta réponse précédente emploie « renormaliser ». {CYCLE}

Confronte ce que tu as affirmé à ces règles, dans le code au besoin. Si c'était faux, ouvre ta réponse en le disant à l'utilisatrice et en le corrigeant. Sinon, n'en dis rien."""

RAPPEL_ECRITURE = f"""Le texte que tu viens d'écrire emploie « renormaliser ». {CYCLE}

Confronte ce que le texte affirme à ces règles, dans le code au besoin. Si c'est faux, corrige le texte et signale-le à l'utilisatrice. Sinon, n'en dis rien."""


def _texte(contenu: object) -> str:
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "\n".join(b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _message_utilisatrice(contenu: object) -> bool:
    """Vrai pour un message de l'utilisatrice : texte brut, ou liste de blocs sans résultat d'outil (message accompagné du contexte de l'IDE)."""
    if isinstance(contenu, str):
        return True
    return (
        isinstance(contenu, list)
        and any(isinstance(b, dict) and b.get("type") == "text" for b in contenu)
        and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in contenu)
    )


def _derniere_reponse(transcript: pathlib.Path) -> str:
    """Texte des messages de Claude depuis le dernier message de l'utilisatrice."""
    morceaux: list[str] = []
    for ligne in transcript.read_text(encoding="utf-8").splitlines():
        try:
            entree = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        message = entree.get("message", {})
        if entree.get("type") == "user" and _message_utilisatrice(message.get("content")):
            morceaux = []
        elif entree.get("type") == "assistant":
            morceaux.append(_texte(message.get("content")))
    return "\n".join(morceaux)


def _texte_ecrit(tool_input: dict) -> str:
    parties = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    parties += [e.get("new_string", "") for e in tool_input.get("edits", []) if isinstance(e, dict)]
    return "\n".join(p for p in parties if isinstance(p, str))


def _contexte(evenement: str, texte: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": evenement, "additionalContext": texte}}))


def main() -> None:
    entree = json.load(sys.stdin)
    evenement = entree.get("hook_event_name")
    if evenement == "UserPromptSubmit":
        transcript = pathlib.Path(entree.get("transcript_path", ""))
        if transcript.is_file() and MOT.search(_derniere_reponse(transcript)):
            _contexte(evenement, RAPPEL_REPONSE)
    elif evenement == "PostToolUse":
        if MOT.search(_texte_ecrit(entree.get("tool_input", {}))):
            _contexte(evenement, RAPPEL_ECRITURE)


if __name__ == "__main__":
    main()
