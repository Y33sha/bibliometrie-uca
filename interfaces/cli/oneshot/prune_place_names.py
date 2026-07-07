"""
Prune `place_name_forms` : supprime les formes (hors `country`) absentes du corpus.

Le seed ROR insère ~191k formes, dont la plupart ne concernent aucune adresse
UCA. On garde celles présentes dans **≥ 1** adresse — y compris des adresses
**déjà résolues** (elles resserviront lors d'un full rerun depuis zéro) — et on
supprime celles à **0** occurrence (bloat pur).

⚠ Critère différent de la détection : on scanne **toutes** les adresses (pas
seulement les sans-pays), via un automate Aho-Corasick au mot près, en traçant
quelles formes matchent.

Les formes `kind = 'country'` sont exclues (matchées en fin de segment, pas par
sous-chaîne — un nom de pays peut être utile sans apparaître au milieu d'une adresse).

Usage :
    python -m interfaces.cli.oneshot.prune_place_names             # supprime
    python -m interfaces.cli.oneshot.prune_place_names --dry-run   # comptes seuls
"""

import argparse
import time

import ahocorasick
from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

logger = setup_logger("prune_place_names", "processing/logs")
BATCH = 10000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Comptes seuls : ne supprime pas")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        forms = [
            r[0]
            for r in conn.execute(
                text("SELECT form_normalized FROM place_name_forms WHERE kind <> 'country'")
            )
        ]
        logger.info(f"{len(forms)} formes (hors country) à vérifier")

        automaton = ahocorasick.Automaton()
        for form in forms:
            if form:
                automaton.add_word(f" {form} ", form)
        automaton.make_automaton()

        norms = [
            r[0]
            for r in conn.execute(
                text("SELECT normalized_text FROM addresses WHERE normalized_text IS NOT NULL")
            )
        ]
        logger.info(f"{len(norms)} adresses à scanner")

        t0 = time.time()
        used: set[str] = set()
        for norm in norms:
            if not norm:
                continue
            for _end, form in automaton.iter(f" {norm} "):
                used.add(form)
        logger.info(f"{len(used)} formes présentes dans ≥ 1 adresse (scan {time.time() - t0:.0f}s)")

        unused = [f for f in forms if f not in used]
        logger.info(f"{len(unused)} formes à supprimer (0 occurrence)")

        if args.dry_run:
            logger.info("Dry-run — retirer --dry-run pour supprimer.")
            return

        for i in range(0, len(unused), BATCH):
            conn.execute(
                text(
                    "DELETE FROM place_name_forms "
                    "WHERE kind <> 'country' AND form_normalized = ANY(:b)"
                ),
                {"b": unused[i : i + BATCH]},
            )
            conn.commit()
        logger.info(f"Pruning terminé : {len(unused)} supprimées, {len(used)} conservées.")


if __name__ == "__main__":
    main()
