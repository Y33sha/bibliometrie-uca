# STATUS: recurring (dev) — 2026-05-08
"""Régénère `domain/hal_domains.py` depuis l'API HAL.

L'API CCSD `https://api.archives-ouvertes.fr/ref/domain/` expose les ~400
domaines HAL au format `<code> = <chemin>/<hiérarchique>`, avec parfois
des annotations `[clé]` (PACS, codes math…) à retirer.

Usage :
    python -m interfaces.cli.dev.refresh_hal_domain_labels

À relancer ponctuellement quand HAL ajoute des domaines (rare). Pas dans
le pipeline régulier.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

API_URL = "https://api.archives-ouvertes.fr/ref/domain/"
DEST = Path(__file__).resolve().parent.parent.parent / "domain" / "hal_domains.py"

_BRACKETS_RE = re.compile(r"\s*\[[^\]]*\]")


def parse_label_s(raw: str) -> tuple[str, str] | None:
    """Parse une entrée `label_s` HAL : `code = chemin/labels`.

    Retourne `(code, feuille_propre)` ou None si format invalide.
    La feuille = dernier segment de `chemin`, annotations entre crochets
    retirées. Exemple :
        "info.info-bi = Informatique [cs]/Bio-informatique [q-bio.QM]"
        -> ("info.info-bi", "Bio-informatique")

    Le code donne la profondeur attendue (N segments séparés par `.`) ;
    on splitte le path par `/` avec `maxsplit=N-1` pour préserver les
    `/` qui font partie d'un nom de feuille (ex "Chimie théorique et/ou
    physique" pour `chim.theo`).
    """
    if " = " not in raw:
        return None
    code, _, path = raw.partition(" = ")
    code = code.strip()
    if not code or not path:
        return None
    depth = code.count(".") + 1
    segments = path.split("/", maxsplit=depth - 1)
    leaf = segments[-1] if segments else path
    leaf = _BRACKETS_RE.sub("", leaf).strip()
    if not leaf:
        return None
    return code, leaf


def fetch_domains() -> list[tuple[str, str]]:
    """Récupère et parse tous les domaines HAL. Retourne une liste triée
    `[(code, label), ...]`."""
    resp = httpx.get(API_URL, params={"wt": "json", "rows": 1000, "fl": "label_s"}, timeout=30)
    resp.raise_for_status()
    docs = resp.json()["response"]["docs"]
    parsed: dict[str, str] = {}
    for doc in docs:
        result = parse_label_s(doc.get("label_s", ""))
        if result:
            code, label = result
            parsed[code] = label
    return sorted(parsed.items())


HEADER = '''"""Référentiel des domaines HAL : code stable → libellé human-readable.

Le dict `HAL_DOMAINS` est généré depuis l'API officielle CCSD via
`interfaces/cli/dev/refresh_hal_domain_labels.py`. La hiérarchie n'est pas
stockée explicitement : elle se reconstitue à partir du code lui-même
(séparateur `.`), évitant la duplication de l'arborescence.

Usage :
    from domain.hal_domains import hal_domain_label, hal_domain_path
    hal_domain_label("chim.anal")   # -> "Chimie analytique"
    hal_domain_path("chim.anal")    # -> "Chimie / Chimie analytique"

Si un code est inconnu (HAL a ajouté un domaine entre deux régénérations
du fichier), les helpers retournent le code tel quel — le pipeline reste
fonctionnel, juste un peu moins lisible jusqu'à la prochaine régénération.
"""

# Chaque entrée : code → libellé feuille (dernier segment du chemin
# hiérarchique HAL, annotations entre crochets retirées).
HAL_DOMAINS: dict[str, str] = {
'''

FOOTER = '''}


def hal_domain_label(code: str) -> str:
    """Libellé human-readable d'un domaine HAL (feuille).

    Fallback sur le code lui-même si inconnu.
    """
    return HAL_DOMAINS.get(code, code)


def hal_domain_path(code: str) -> str:
    """Chemin hiérarchique reconstruit depuis le code.

    Splitte le code par `.` pour obtenir les ancêtres et compose le chemin
    `parent / ... / feuille` en mappant chaque préfixe via `HAL_DOMAINS`.
    Fallback sur le code lui-même pour les segments inconnus.
    """
    parts = code.split(".")
    if not parts:
        return code
    labels = []
    for i in range(1, len(parts) + 1):
        prefix = ".".join(parts[:i])
        labels.append(HAL_DOMAINS.get(prefix, prefix))
    return " / ".join(labels)
'''


def main() -> None:
    domains = fetch_domains()
    print(f"Récupéré {len(domains)} domaines HAL")
    lines = [HEADER]
    for code, label in domains:
        # repr() gère les apostrophes, accents, etc.
        lines.append(f"    {code!r}: {label!r},\n")
    lines.append(FOOTER)
    DEST.write_text("".join(lines), encoding="utf-8")
    print(f"Écrit {DEST}")


if __name__ == "__main__":
    main()
