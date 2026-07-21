# STATUS: oneshot (2026-06-22)
"""Détachement rétrospectif des rattachements identifiant à nom incompatible (corruption éparse).

Applique au stock le garde de corroboration par le nom ajouté à la cascade
(`decide_match_by_identifier`) : un rattachement tenu par un identifiant alors que la
signature est incompatible avec le nom de la personne ciblée est une erreur d'attribution
d'identifiant. La phase persons étant **incrémentale** (`WHERE person_id IS NULL`), elle ne
ré-évalue pas d'elle-même les liens déjà posés ; on les détache en nullant leur `person_id`.

Périmètre **volontairement restreint** au cas à haute confiance, pour ne pas scinder des
identités légitimes (changement de nom : « Van Lander » portant l'identifiant de « Maneval ») :
on ne détache une signature-intrus (nom incompatible + identifiant résolvant vers sa personne)
que si la **même `source_publication`** porte aussi une autre signature rattachée à cette même
personne sous un nom **compatible** (le porteur légitime). Cette double occurrence prouve que la
signature-intrus est étrangère, pas un changement de nom. Le reste (intrus sans porteur légitime)
est la zone grise laissée à révision, non détachée d'office.

Séquence (calquée sur `remediate_dubious_agglomerations`) :

1. **Null `person_id`** des intrus confirmés — fenêtré par `source_publication_id` (toutes les
   signatures d'une publi partagent le même id, donc le couple intrus/porteur est local à la
   fenêtre). Critère évalué en Python (`names_compatible` + résolution d'identifiant).
2. **Purge des `person_identifiers` `status='pending'` orphelins** (plus aucune signature de la
   personne ne porte la valeur). Les `confirmed`/`rejected` (verdicts humains) sont préservés.
3. **Recalcul `person_name_forms`** : le diff supprime les formes héritées des signatures nullées.

Ensuite : **relancer le pipeline** (phase persons). `create_persons` ré-attribue les signatures
nullées, le garde refusant cette fois l'identifiant fautif.

Usage :
    python -m interfaces.cli.oneshot.remediate_identifier_name_incompatible [--dry-run] [--window 2000]
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from sqlalchemy import Connection, text

from application.pipeline.persons.populate_person_name_forms import populate
from domain.persons.matching import ORCID_MATCH_SOURCES
from domain.persons.name_matching import names_compatible
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.persons.name_forms import PgPersonNameFormsQueries

log = setup_logger("remediate_identifier_name_incompatible", os.path.dirname(__file__))

ID_TYPES = ("orcid", "idref", "hal_person_id")

_MAX_PUB_SQL = text("SELECT max(source_publication_id) FROM source_authorships")

# Signatures liées de la fenêtre courante, avec leurs identifiants (non `_dubious`, lus par clé
# nue) et le nom normalisé de la personne rattachée.
_LINKED_SQL = text("""
    SELECT sa.id,
           sa.source_publication_id AS spid,
           sa.person_id,
           sa.source::text AS source,
           sa.raw_author_name AS name,
           aik.person_identifiers->>'orcid' AS orcid,
           aik.person_identifiers->>'idref' AS idref,
           aik.person_identifiers->>'hal_person_id' AS hal_person_id,
           p.last_name_normalized AS pln,
           p.first_name_normalized AS pfn
    FROM source_authorships sa
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    JOIN persons p ON p.id = sa.person_id
    WHERE sa.source_publication_id > :last
      AND sa.source_publication_id <= :hi
      AND sa.person_id IS NOT NULL
      AND sa.raw_author_name IS NOT NULL
""")

_NULL_SQL = text("UPDATE source_authorships SET person_id = NULL WHERE id = ANY(:ids)")

_PURGE_SQL = text("""
    DELETE FROM person_identifiers pi
    WHERE pi.status = 'pending'
      AND NOT EXISTS (
          SELECT 1 FROM source_authorships sa
          JOIN author_identifying_keys aik ON aik.id = sa.identity_id
          WHERE sa.person_id = pi.person_id
            AND aik.person_identifiers ->> (pi.id_type)::text = pi.id_value
      )
""")


def _load_id_map(conn: Connection, id_type: str) -> dict[str, int]:
    """`{id_value: person_id}` pour les identifiants connus non rejetés."""
    rows = conn.execute(
        text(
            "SELECT id_value, person_id FROM person_identifiers "
            "WHERE id_type = :t AND status <> 'rejected'"
        ),
        {"t": id_type},
    ).all()
    return {r.id_value: r.person_id for r in rows}


def _id_resolves_to_linked_person(maps: dict[str, dict[str, int]], row: Any) -> bool:
    """Un identifiant porté par la signature résout-il vers la personne déjà rattachée ?

    C'est ce qui signe que le rattachement est tenu par l'identifiant (le nom ne pouvait pas
    le produire, il est incompatible). L'ORCID n'est un signal que pour les sources à dépôt
    auteur (`ORCID_MATCH_SOURCES`), comme dans la cascade."""
    if (
        row.orcid
        and row.source in ORCID_MATCH_SOURCES
        and maps["orcid"].get(row.orcid) == row.person_id
    ):
        return True
    if row.idref and maps["idref"].get(row.idref) == row.person_id:
        return True
    if row.hal_person_id and maps["hal_person_id"].get(row.hal_person_id) == row.person_id:
        return True
    return False


def _detach(
    conn: Connection, maps: dict[str, dict[str, int]], window: int, dry_run: bool
) -> tuple[int, list[tuple[str, str]]]:
    max_pub = conn.execute(_MAX_PUB_SQL).scalar() or 0
    total = 0
    samples: list[tuple[str, str]] = []
    last = 0
    while last < max_pub:
        hi = last + window
        rows = conn.execute(_LINKED_SQL, {"last": last, "hi": hi}).all()

        legit: set[tuple[int, int]] = (
            set()
        )  # (spid, person_id) avec une signature au nom compatible
        candidates = []  # (id, spid, person_id, name, target_name) : intrus identifiant
        for r in rows:
            if names_compatible(r.name, "", r.pln, r.pfn):
                legit.add((r.spid, r.person_id))
            elif _id_resolves_to_linked_person(maps, r):
                candidates.append((r.id, r.spid, r.person_id, r.name, f"{r.pfn} {r.pln}".strip()))

        ids = [c[0] for c in candidates if (c[1], c[2]) in legit]
        for c in candidates:
            if (c[1], c[2]) in legit and len(samples) < 20:
                samples.append((c[3], c[4]))

        if ids and not dry_run:
            conn.execute(_NULL_SQL, {"ids": ids})
            conn.commit()
        total += len(ids)
        last = hi
        if (last // window) % 50 == 0:
            log.info("… curseur=%d/%d, %d intrus confirmés", last, max_pub, total)
    return total, samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans écrire ni recalculer.")
    parser.add_argument(
        "--window", type=int, default=2000, help="Largeur de la fenêtre d'ids de publication."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        maps = {t: _load_id_map(conn, t) for t in ID_TYPES}
        log.info("Maps identifiants : " + ", ".join(f"{t}={len(maps[t])}" for t in ID_TYPES))

        total, samples = _detach(conn, maps, args.window, args.dry_run)
        log.info("1/3 — %d person_id %s", total, "à nuller" if args.dry_run else "nullés")
        for name, target in samples:
            log.info("    intrus %r détaché de la personne %r", name, target)

        if args.dry_run:
            log.info("2/3 — purge person_identifiers pending orphelins (sautée en dry-run)")
            log.info("3/3 — recalcul person_name_forms (sauté en dry-run)")
            log.info("DRY-RUN : aucune écriture")
            return 0

        n_purged = conn.execute(_PURGE_SQL).rowcount
        conn.commit()
        log.info("2/3 — %d person_identifiers pending orphelins supprimés", n_purged)

        log.info("3/3 — recalcul person_name_forms…")
        populate(conn, PgPersonNameFormsQueries(), log)
        conn.commit()

    log.info("Terminé. Relancer le pipeline (phase persons) pour la ré-attribution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
