"""Supprime des `place_name_forms` génériques + recompute les adresses touchées.

Complément de `prune_place_names` (formes absentes du corpus) et de
`validate_place_names` (formes au pays minoritaire) : ici on retire des formes
**génériques** (mots de domaine, types d'établissement, titres) qui sont
correctement géolocalisées mais trop peu spécifiques — ex. `nutrition`,
`hopital`, `centre hospitalier universitaire`, `maitre de conferences`. Dans un
corpus très francophone, leur pays (souvent fr) reste *majoritaire*, donc
`validate_place_names` ne les voit pas ; mais elles matchent aussi des adresses
étrangères (Genève, Bruxelles, Montréal…) → faux conflit multi-pays → la
détection autoritaire s'auto-annule (mesurée : 0 résolution sur ~21k adresses
sans pays, ~4400 perdues sur conflit).

Liste **curée à la main** (`GENERIC_FORMS`) à partir des formes les plus
matchantes et les plus présentes dans les conflits — éditable.

Effets (`--apply`) :
  1. NULL `countries` + `suggested_countries` des adresses contenant (au mot près)
     l'une de ces formes → à recalculer "à propre" par la phase `countries`.
  2. Suppression des formes de `place_name_forms`.

À enchaîner avec un run de la phase `countries` (detect → suggest → refresh) pour
ré-résoudre les adresses libérées du conflit.

Usage :
    python -m interfaces.cli.oneshot.prune_generic_place_names              # applique
    python -m interfaces.cli.oneshot.prune_generic_place_names --dry-run    # compte seulement
"""

import argparse

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

logger = setup_logger("prune_generic_place_names", "processing/logs")

# Formes génériques à retirer (mots communs, types d'établissement, titres).
# Curée depuis les formes les plus matchantes / les plus présentes en conflit.
GENERIC_FORMS = [
    "innovation",
    "hopital",
    "territoires",
    "evolution",
    "association",
    "university school",
    "columbia",
    "laboratoire de mathematiques",
    "centre hospitalier universitaire",
    "ressources",
    "maitre de conferences",
    "doctorante",
    "architecture",
    "sante publique",
    "clinical immunology",
    # 2e passe : queue de génériques résiduels (mots communs, domaines, types).
    "particulier",
    "autres",
    "savoirs",
    "hepatology",
    "neurosurgery",
    "college of medicine",
    "faculty of physics",
    "mathematiques appliquees",
    "human nutrition unit",
    "division of human nutrition",
    "agriculture and food",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien modifier.")
    args = parser.parse_args()

    with get_sync_engine().connect() as conn:
        present = {
            r.form_normalized
            for r in conn.execute(
                text(
                    "SELECT form_normalized FROM place_name_forms WHERE form_normalized = ANY(:f)"
                ),
                {"f": GENERIC_FORMS},
            )
        }
        absent = sorted(set(GENERIC_FORMS) - present)
        logger.info(
            "%d/%d formes présentes dans place_name_forms", len(present), len(GENERIC_FORMS)
        )
        if absent:
            logger.info("  (déjà absentes : %s)", ", ".join(absent))
        if not present:
            logger.info("Rien à supprimer.")
            return

        # On ne nulle QUE les adresses des formes réellement supprimées ce run : une
        # forme déjà absente n'affecte plus la détection, ses adresses sont déjà
        # recalculées (inutile de les re-nuller). Idempotent + incrémental.
        patterns = [f"% {f} %" for f in sorted(present)]
        # Match au mot près (espaces encadrants), comme le détecteur Aho-Corasick.
        n_addr = conn.execute(
            text(
                "SELECT count(*) FROM addresses "
                "WHERE (' ' || normalized_text || ' ') LIKE ANY(:p) "
                "AND (countries IS NOT NULL OR suggested_countries IS NOT NULL)"
            ),
            {"p": patterns},
        ).scalar_one()
        logger.info("%d adresses (avec pays/suggestion) à nuller pour recalcul", n_addr)

        if args.dry_run:
            logger.info("DRY-RUN — lancer sans --dry-run pour appliquer.")
            return

        nulled = conn.execute(
            text(
                "UPDATE addresses SET countries = NULL, suggested_countries = NULL "
                "WHERE (' ' || normalized_text || ' ') LIKE ANY(:p) "
                "AND (countries IS NOT NULL OR suggested_countries IS NOT NULL)"
            ),
            {"p": patterns},
        ).rowcount
        deleted = conn.execute(
            text("DELETE FROM place_name_forms WHERE form_normalized = ANY(:f)"),
            {"f": GENERIC_FORMS},
        ).rowcount
        conn.commit()
        logger.info("✓ %d formes supprimées, %d adresses nullées", deleted, nulled)
        logger.info("→ relancer la phase `countries` pour ré-résoudre.")


if __name__ == "__main__":
    main()
