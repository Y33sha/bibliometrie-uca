"""Backfill publications.sources après le fix bulk_link_orphans

Recalcule `publications.sources` depuis l'agrégation des
`source_publications` rattachés. Cible : ~16 000 publications dont
l'array `sources` ne reflète pas les SP réellement rattachées (cas
dominant : crossref manquant dans l'array alors qu'au moins un SP
crossref est rattaché à la pub).

Cause : entre l'introduction de la Phase B (bulk_link set-based des
orphelins hors-périmètre) et le fix `b0661244` du 2026-05-28, les trois
`bulk_link_orphans_by_*` rattachaient sans bumper `sp.updated_at`. La
fenêtre de staleness restait fermée → `fetch_stale_publication_ids` ne
remontait pas ces publications en Phase 2 → `refresh_from_sources` ne
jouait jamais → `update_sources` non plus.

Le one-shot `refresh_publications_stale_oa_status` (2026-05-28) a
rattrapé `oa_status` sur 2117 pubs mais sa population cible était
spécifique à OA_RANK : il n'a pas couvert les pubs dont seule l'array
`sources` était désynchronisée. D'où ce backfill complémentaire.

SQL set-based : un seul UPDATE. La sous-requête réagrège `sources`
depuis `source_publications` pour chaque publication ayant ≥1 SP
rattachée, et `IS DISTINCT FROM` filtre aux seules pubs effectivement
discordantes (incluant le cas où l'ordre des éléments diffère — l'UPDATE
normalise alors à l'ordre canonique `ORDER BY source`, identique à celui
de `update_sources` côté repo).

Les pubs sans aucun SP rattaché (orphelines) ne sont pas touchées : la
règle métier veut qu'elles n'existent pas, leur traitement relève d'un
nettoyage séparé (`refresh_from_sources` les supprimerait).

Revision ID: e8b6c4f9d2a1
Revises: 07faedd93347
Create Date: 2026-05-29 11:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e8b6c4f9d2a1"
down_revision: str | Sequence[str] | None = "07faedd93347"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE public.publications p
        SET sources = sub.srcs,
            updated_at = now()
        FROM (
            SELECT publication_id,
                   array_agg(DISTINCT source ORDER BY source) AS srcs
            FROM public.source_publications
            WHERE publication_id IS NOT NULL
            GROUP BY publication_id
        ) sub
        WHERE p.id = sub.publication_id
          AND p.sources IS DISTINCT FROM sub.srcs
        """
    )


def downgrade() -> None:
    # L'état précédent de `sources` n'est pas conservé : le backfill
    # remplace une valeur désynchronisée par la valeur agrégée correcte.
    # Rollback non implémenté.
    raise NotImplementedError(
        "Backfill publications.sources : état précédent non conservé, rollback non implémenté"
    )
