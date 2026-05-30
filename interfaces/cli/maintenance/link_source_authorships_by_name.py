# STATUS: oneshot (2026-05-30)
"""Rattache aux person canoniques les `source_authorships` orphelines
quand un person canonique existe deja sur la meme publication a la meme
position avec un `author_name_normalized` strictement identique.

Bootstrap transitoire qui comble le trou de la phase persons sur les SA
hors-perimetre : la cascade actuelle ne traite que les SA
`in_perimeter = TRUE`, donc une SA OpenAlex/CrossRef qui n'a pas detecte
UCA reste orpheline alors qu'un person UCA est identifie par HAL a la
meme position. Cf. fiche `METIER_authorships-cross-source-matching`.

Criteres stricts (zero tolerance, alignes sur la decision du chantier) :

- position exacte (`author_position` egale entre la SA orpheline et la
  SA de reference) ;
- egalite stricte de `author_name_normalized`.

Effets de bord, alignes sur la cascade `decide_person_match` action
`match` :

- UPDATE `source_authorships.person_id` et `authorship_id` ;
- pour chaque SA rattachee, propagation des identifiants observes
  (`orcid`, `idhal`, `idref`, `hal_person_id`) vers `person_identifiers`
  via `add_identifiers_from_authorships` (statut `pending`, conflits
  logges en warning) ;
- `add_name_form` n'est PAS appele : le nom est strictement identique
  par construction, la name_form existe deja sur la person ;
- `source_authorships.in_perimeter` n'est PAS modifie : la valeur
  reflete honnetement la detection par chaque source. Un auteur UCA-CHU
  qui ne signe que CHU dans OpenAlex doit rester `in_perimeter = FALSE`
  cote SA OA. Seul l'appariement person est complete.

Cas pathologique : si pour un meme (publication, position, nom
normalise) plusieurs `person_id` canoniques distincts sont candidats,
on skip cette SA et on log les person_ids concernes -- signal fort de
doublon de person dans la base, a investiguer via l'admin
`/admin/person-duplicates`.

Idempotent : un re-run ne retraite que les nouvelles SA orphelines.

Usage :
    python -m interfaces.cli.maintenance.link_source_authorships_by_name [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from application.persons import add_identifiers_from_authorships
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("link_source_authorships_by_name", os.path.dirname(__file__))


# CTE de base : tous les triplets (orphan_sa_id, person_id candidat,
# authorship_id candidat) pour chaque SA orpheline matchant un authorship
# canonique sur (publication, position, nom normalise). Une meme SA peut
# apparaitre plusieurs fois si plusieurs SA d'autres sources convergent sur le
# meme triplet (idempotent par DISTINCT ensuite) -- ou diverger sur des
# `person_id` differents, ce qui est le cas pathologique signale.
_BASE_CTE = """
    WITH linked AS (
        SELECT a.id AS authorship_id, a.publication_id, a.person_id, a.author_position
        FROM authorships a
        WHERE a.person_id IS NOT NULL AND a.author_position IS NOT NULL
    ),
    groups AS (
        SELECT orphan.id AS orphan_sa_id,
               orphan.person_identifiers AS orphan_identifiers,
               linked.publication_id,
               linked.author_position,
               orphan.author_name_normalized AS norm,
               linked.person_id,
               linked.authorship_id
        FROM source_authorships orphan
        JOIN source_publications sp ON sp.id = orphan.source_publication_id
        JOIN linked
            ON linked.publication_id = sp.publication_id
           AND linked.author_position = orphan.author_position
        JOIN source_authorships linked_sa
            ON linked_sa.authorship_id = linked.authorship_id
           AND linked_sa.author_name_normalized = orphan.author_name_normalized
        WHERE orphan.person_id IS NULL
          AND orphan.author_name_normalized IS NOT NULL
    ),
    unambig_keys AS (
        SELECT publication_id, author_position, norm
        FROM groups
        GROUP BY publication_id, author_position, norm
        HAVING COUNT(DISTINCT person_id) = 1
    )
"""

_AMBIGUOUS_SQL = (
    _BASE_CTE
    + """
    SELECT publication_id, author_position, norm,
           ARRAY_AGG(DISTINCT person_id ORDER BY person_id) AS person_ids
    FROM groups
    GROUP BY publication_id, author_position, norm
    HAVING COUNT(DISTINCT person_id) > 1
    ORDER BY publication_id, author_position;
"""
)

_FETCH_TO_LINK_SQL = (
    _BASE_CTE
    + """
    SELECT DISTINCT
        g.orphan_sa_id,
        g.person_id,
        g.authorship_id,
        g.orphan_identifiers
    FROM groups g
    JOIN unambig_keys u
        ON u.publication_id = g.publication_id
       AND u.author_position = g.author_position
       AND u.norm = g.norm;
"""
)


_UPDATE_SQL = (
    "UPDATE source_authorships SET person_id = :person_id, "
    "authorship_id = :authorship_id WHERE id = :sa_id"
)


def _identifier_dict(orphan_identifiers: dict | None) -> dict[str, object]:
    """Adapte le jsonb `source_authorships.person_identifiers` au format
    dict attendu par `add_identifiers_from_authorships` (cle `id_type` =
    valeur)."""
    if not orphan_identifiers:
        return {}
    return {
        "orcid": orphan_identifiers.get("orcid"),
        "idhal": orphan_identifiers.get("idhal"),
        "idref": orphan_identifiers.get("idref"),
        "hal_person_id": orphan_identifiers.get("hal_person_id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="N'ecrit rien : compte les SA qui seraient rattachees.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        ambiguous = conn.execute(text(_AMBIGUOUS_SQL)).all()
        if ambiguous:
            log.warning(
                "%d cas ambigus (plusieurs person_id distincts pour un meme"
                " (publication, position, nom normalise)) -- doublons person"
                " probables, a investiguer dans /admin/person-duplicates :",
                len(ambiguous),
            )
            for a in ambiguous:
                log.warning(
                    "  pub=%d pos=%d norm='%s' person_ids=%s",
                    a.publication_id,
                    a.author_position,
                    a.norm,
                    a.person_ids,
                )
        else:
            log.info("Aucun cas ambigu detecte.")

        to_link = conn.execute(text(_FETCH_TO_LINK_SQL)).all()
        log.info("%d SA candidates au rattachement.", len(to_link))

        if args.dry_run:
            with_ids = sum(1 for r in to_link if r.orphan_identifiers)
            log.info(
                "(dry-run) dont %d porteuses d'au moins un identifiant a propager.",
                with_ids,
            )
            return 0

        params = [
            {
                "sa_id": r.orphan_sa_id,
                "person_id": r.person_id,
                "authorship_id": r.authorship_id,
            }
            for r in to_link
        ]
        if params:
            conn.execute(text(_UPDATE_SQL), params)
        log.info("UPDATE applique sur %d SA.", len(params))

        repo = person_repository(conn)
        n_with_ids = 0
        for r in to_link:
            ids = _identifier_dict(r.orphan_identifiers)
            if not any(ids.values()):
                continue
            add_identifiers_from_authorships(r.person_id, [ids], repo=repo)
            n_with_ids += 1
        log.info("Identifiants propages depuis %d SA.", n_with_ids)

        conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
