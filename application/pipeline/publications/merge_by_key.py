"""Helper unifié pour fusionner les publications par clé de déduplication.

Consolide les sites de fusion par identifiant unique (NNT, hal_id, …). Pour chaque batch de `pub_ids` partageant la même clé, choisit le minimum stable comme cible et fusionne les autres dedans, en suivant les redirections accumulées dans le batch (si A a été mergée dans B, et qu'on rencontre ensuite X à merger avec A, on redirige automatiquement vers B).

Choix de cible trivial (`min(pub_ids)`) : les métadonnées canoniques étant triangulées par `refresh_from_sources` après chaque fusion, le choix de la cible n'a pas d'impact métier (cf. décision 3 du chantier `METIER_deduplication-fusion-publications`).
"""

import logging
from collections.abc import Iterable

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import merge_publications, refresh_from_sources


def merge_publications_by_key(
    conn: Connection,
    groups: Iterable[tuple[str, list[int]]],
    *,
    logger: logging.Logger,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Fusionne par batches les publications regroupées par clé de déduplication.

    `groups` est un itérable de `(key_label, pub_ids)` où `key_label` sert au logging (ex. `"NNT=2023UCFA0001"` ou `"hal-04123456"`) et `pub_ids` est la liste des `publication.id` qui doivent toutes converger vers une seule.

    Pour chaque groupe : résout les redirections déjà accumulées dans le batch, choisit le `min` des id résolus comme cible, fusionne les autres dedans (un par un, savepoint individuel pour permettre la continuation après échec).

    Retourne `(merged, errors)`. Chaque fusion réussie incrémente `merged` ; chaque exception incrémente `errors` (loggée en warning, le batch continue).
    """
    redirects: dict[int, int] = {}

    def resolve(pub_id: int) -> int:
        seen: set[int] = set()
        while pub_id in redirects:
            if pub_id in seen:
                break
            seen.add(pub_id)
            pub_id = redirects[pub_id]
        return pub_id

    merged = 0
    errors = 0

    for key_label, pub_ids in groups:
        resolved_ids = sorted({resolve(pid) for pid in pub_ids})
        if len(resolved_ids) < 2:
            # Toutes les pubs du groupe ont déjà été redirigées vers une seule.
            continue

        target_id = resolved_ids[0]
        to_merge = resolved_ids[1:]

        for source_id in to_merge:
            label = f"{key_label} : pub {source_id} → {target_id}"

            if dry_run:
                logger.info(f"  [DRY] {label}")
                merged += 1
                continue

            try:
                with savepoint(conn, "merge_by_key"):
                    merge_publications(target_id, source_id, repo=pub_repo)
                    refresh_from_sources(target_id, repo=pub_repo)
                redirects[source_id] = target_id
                merged += 1
                logger.info(f"  [MERGE] {label}")
            except Exception as e:
                logger.warning(f"  Échec {label}: {e}")
                errors += 1

    return merged, errors
