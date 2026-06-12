"""
Valide `place_name_forms` contre le corpus : retire les formes mal attribuées.

Complément de `prune_place_names` (qui retire les formes **absentes** du corpus) :
ici on retire les formes **présentes mais dont le pays assigné contredit le
corpus**. Pour chaque forme (hors `country`), on regarde les adresses résolues
mono-pays qui la contiennent comme sous-chaîne (automate Aho-Corasick au mot
près) ; si le pays assigné y est **minoritaire** (part < seuil) avec un support
suffisant, la forme est parasite — mot de domaine (`biology`, `cardiology`),
générique d'institution (`centre hospitalier`, `research institute`) ou mal
géolocalisée (`chinese academy` → tw alors que cn à 97 %). Ces formes faussent la
détection autoritaire : faux conflits multi-pays qui bloquent des résolutions
légitimes, et fausses résolutions quand elles matchent seules.

Le seuil par défaut (part du pays assigné < 50 %) exige qu'une forme autoritaire
ait son pays assigné au moins majoritaire parmi ses occurrences réelles.

Usage :
    python -m interfaces.cli.oneshot.validate_place_names            # dry-run (comptes)
    python -m interfaces.cli.oneshot.validate_place_names --apply    # supprime
"""

import argparse
import time
from collections import Counter, defaultdict

import ahocorasick
from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

logger = setup_logger("validate_place_names", "processing/logs")

MIN_SUPPORT = 5
MAX_SHARE = 0.5
DELETE_BATCH = 10000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Supprimer (sinon dry-run)")
    parser.add_argument("--min-support", type=int, default=MIN_SUPPORT)
    parser.add_argument("--max-share", type=float, default=MAX_SHARE)
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        forms = {
            r.form_normalized: r.iso_code
            for r in conn.execute(
                text(
                    "SELECT form_normalized, iso_code FROM place_name_forms WHERE kind <> 'country'"
                )
            )
        }
        logger.info(f"{len(forms)} formes (hors country) à valider")

        automaton = ahocorasick.Automaton()
        for form in forms:
            if form:
                automaton.add_word(f" {form} ", form)
        automaton.make_automaton()

        # Vérité terrain : pour chaque forme, distribution des pays de ses adresses
        # résolues mono-pays.
        form_countries: dict[str, Counter] = defaultdict(Counter)
        t0 = time.time()
        scanned = 0
        scan = text(
            "SELECT normalized_text, countries FROM addresses "
            "WHERE countries IS NOT NULL AND cardinality(countries) = 1 "
            "AND normalized_text IS NOT NULL"
        ).execution_options(stream_results=True)
        for txt, countries in conn.execute(scan):
            country = countries[0]
            for _end, form in automaton.iter(f" {txt} "):
                form_countries[form][country] += 1
            scanned += 1
        logger.info(f"{scanned} adresses résolues scannées ({time.time() - t0:.0f}s)")

        parasites = []
        for form, iso in forms.items():
            distribution = form_countries.get(form)
            if not distribution:
                continue  # absente des adresses résolues → non jugeable ici (cf. prune)
            total = sum(distribution.values())
            if total >= args.min_support and distribution[iso] / total < args.max_share:
                parasites.append(form)
        logger.info(
            f"{len(parasites)} formes parasites "
            f"(support >= {args.min_support}, part du pays assigné < {args.max_share:.0%})"
        )

        if not args.apply:
            logger.info("Dry-run — ajouter --apply pour supprimer.")
            return

        for i in range(0, len(parasites), DELETE_BATCH):
            conn.execute(
                text(
                    "DELETE FROM place_name_forms "
                    "WHERE kind <> 'country' AND form_normalized = ANY(:b)"
                ),
                {"b": parasites[i : i + DELETE_BATCH]},
            )
            conn.commit()
        logger.info(f"Validation terminée : {len(parasites)} formes parasites retirées.")


if __name__ == "__main__":
    main()
