# STATUS: oneshot (2026-08-31)
"""Remet à jour les empreintes de commit citées dans la documentation après une réécriture d'historique.

`git filter-repo` dépose la correspondance ancienne → nouvelle empreinte dans `.git/filter-repo/commit-map`. Les fiches de chantier citent des commits par un préfixe de sept à quarante caractères ; ce script y substitue le nouveau préfixe, de même longueur.

Écrit dans les fichiers. `--dry-run` se contente d'énumérer les substitutions.
"""

from __future__ import annotations

import argparse
import re

from infrastructure import PROJECT_ROOT

COMMIT_MAP = PROJECT_ROOT / ".git" / "filter-repo" / "commit-map"
DOCUMENTATION = PROJECT_ROOT / "docs"
EMPREINTE = re.compile(r"\b[0-9a-f]{7,40}\b")
ZERO = "0" * 40


def charger_correspondance() -> dict[str, str]:
    """Table ancienne → nouvelle empreinte, les commits supprimés écartés."""
    correspondance: dict[str, str] = {}
    for ligne in COMMIT_MAP.read_text().splitlines():
        champs = ligne.split()
        if len(champs) != 2:
            continue
        ancienne, nouvelle = champs
        if ancienne == "old" or nouvelle == ZERO or ancienne == nouvelle:
            continue
        correspondance[ancienne] = nouvelle
    return correspondance


def substituer(texte: str, correspondance: dict[str, str]) -> tuple[str, int]:
    """Texte dont chaque préfixe d'empreinte reconnu porte sa valeur d'arrivée, à longueur égale, et le nombre de substitutions."""
    compte = 0

    def valeur_d_arrivee(m: re.Match[str]) -> str:
        nonlocal compte
        cite = m.group(0)
        for ancienne, nouvelle in correspondance.items():
            if ancienne.startswith(cite):
                compte += 1
                return nouvelle[: len(cite)]
        return cite

    return EMPREINTE.sub(valeur_d_arrivee, texte), compte


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="énumère sans écrire")
    args = parser.parse_args()

    correspondance = charger_correspondance()
    print(f"{len(correspondance)} commits déplacés par la réécriture")

    total = 0
    for fichier in sorted(DOCUMENTATION.rglob("*.md")):
        contenu = fichier.read_text()
        rendu, compte = substituer(contenu, correspondance)
        if compte:
            total += compte
            print(f"  {fichier.relative_to(PROJECT_ROOT)} : {compte}")
            if not args.dry_run:
                fichier.write_text(rendu)
    print(f"{total} références {'à mettre à jour' if args.dry_run else 'mises à jour'}")


if __name__ == "__main__":
    main()
