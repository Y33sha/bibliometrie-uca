"""Rappelle le cycle extraction / normalisation / raw store quand Claude emploie le mot « renormaliser ».

- `Stop` : si la dernière réponse de Claude emploie le mot, la fin de tour est bloquée et le rappel lui est renvoyé, pour qu'il vérifie son affirmation et la corrige au besoin. Un seul renvoi par fin de tour (`stop_hook_active`).
- `PostToolUse` (`Write`, `Edit`, `MultiEdit`) : si le texte écrit emploie le mot, le rappel est ajouté au contexte de Claude, sans bloquer l'écriture.
"""

import json
import pathlib
import re
import sys

MOT = re.compile(r"renormalis", re.IGNORECASE)

RAPPEL = """Tu viens d'employer « renormaliser ». Rappel du cycle, à confronter à ce que tu as affirmé :

- `extract` upsert les payloads des sources dans `staging`. Une ligne repasse à `processed = FALSE` seulement si son payload a changé (`raw_hash` distinct), ou quand `fetch_truncated` la complète.
- `normalize` traite seulement les lignes `processed = FALSE`. Avec `--raw-store`, `mark_done` archive le payload dans le raw store, puis vide `raw_data`.
- Une notice déjà normalisée ne repasse donc pas par `normalize` d'elle-même. Rejouer la normalisation d'un stock passe par `interfaces/cli/maintenance/rehydrate_staging_from_raw_store.py`.
- `--normalize-full` ne remet aucune notice en file : il force la synchronisation des signatures des seules notices traitées pendant ce passage, même à bloc auteurs inchangé.

Vérifie ton affirmation contre ces règles, dans le code au besoin. Si elle est fausse, dis-le explicitement à l'utilisatrice et corrige-la. Si elle est juste, termine sans rien écrire."""


def _texte(contenu: object) -> str:
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "\n".join(b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _derniere_reponse(transcript: pathlib.Path) -> str:
    """Texte des messages de Claude depuis le dernier message de l'utilisatrice."""
    morceaux: list[str] = []
    for ligne in transcript.read_text(encoding="utf-8").splitlines():
        try:
            entree = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        message = entree.get("message", {})
        if entree.get("type") == "user" and isinstance(message.get("content"), str):
            morceaux = []
        elif entree.get("type") == "assistant":
            morceaux.append(_texte(message.get("content")))
    return "\n".join(morceaux)


def _texte_ecrit(tool_input: dict) -> str:
    parties = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    parties += [e.get("new_string", "") for e in tool_input.get("edits", []) if isinstance(e, dict)]
    return "\n".join(p for p in parties if isinstance(p, str))


def main() -> None:
    entree = json.load(sys.stdin)
    evenement = entree.get("hook_event_name")
    if evenement == "Stop":
        if entree.get("stop_hook_active"):
            return
        transcript = pathlib.Path(entree.get("transcript_path", ""))
        if transcript.is_file() and MOT.search(_derniere_reponse(transcript)):
            print(json.dumps({"decision": "block", "reason": RAPPEL}))
    elif evenement == "PostToolUse":
        if MOT.search(_texte_ecrit(entree.get("tool_input", {}))):
            print(
                json.dumps(
                    {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": RAPPEL}}
                )
            )


if __name__ == "__main__":
    main()
