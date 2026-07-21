"""Query service : écriture des `source_publications`, commune à toutes les sources.

Implémente `application.ports.pipeline.normalize.source_publications.SourcePublicationQueries`.

Une `source_publication` est la vue normalisée d'un import : le dernier import fait autorité. L'UPSERT réécrit donc toutes les colonnes de l'enregistrement depuis la ligne fournie, sans conserver de valeur antérieure. Seule l'identité `(source, source_id)` traverse les imports, ce qui maintient l'`id` de la ligne stable pour les tables qui la référencent — d'où l'UPSERT plutôt qu'un DELETE suivi d'un INSERT.

L'écriture ne porte que sur les colonnes de la ligne : celles qu'aucun import ne renseigne traversent l'UPSERT intactes. C'est le cas de `publication_id`, que la phase `publications` pose et recalcule pour les lignes marquées `keys_dirty` — ce que chaque écriture fait ici. C'est aussi le cas du cache `countries`, alimenté par la phase du même nom, et de `created_at`.
"""

from dataclasses import fields
from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.normalize.source_publications import (
    SourcePublicationQueries,
    SourcePublicationRow,
)
from domain.publications.metadata import normalized_title

_ROW_FIELDS = tuple(f.name for f in fields(SourcePublicationRow))

# Les colonnes écrites se dérivent des champs de la ligne, plus `title_normalized`
# calculé à l'écriture : un champ ajouté à `SourcePublicationRow` est inséré et
# réécrit sans autre geste, en phase avec le contrat.
_COLUMNS = (*_ROW_FIELDS, "title_normalized")

# Tout est réécrit sauf la clé de conflit, qui est justement ce qui identifie la ligne.
_UPDATED_COLUMNS = tuple(c for c in _COLUMNS if c not in ("source", "source_id"))

_UPSERT_SQL = text(
    f"""
    INSERT INTO source_publications ({", ".join(_COLUMNS)})
    VALUES ({", ".join(f":{c}" for c in _COLUMNS)})
    ON CONFLICT (source, source_id) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATED_COLUMNS)},
        keys_dirty = true,
        updated_at = clock_timestamp()
    RETURNING id
    """  # noqa: S608 — listes de colonnes construites depuis le contrat, sans entrée externe
).bindparams(
    bindparam("external_ids", type_=JSONB),
    bindparam("biblio", type_=JSONB),
    bindparam("topics", type_=JSONB),
    bindparam("meta", type_=JSONB),
)


def upsert_source_publication(conn: Connection, row: SourcePublicationRow) -> int:
    """UPSERT d'un enregistrement source sur la clé `(source, source_id)`. Retourne l'id de la ligne."""
    params: dict[str, Any] = {name: getattr(row, name) for name in _ROW_FIELDS}
    params["title_normalized"] = normalized_title(row.title)
    # `external_ids` est `NOT NULL` et contraint à un objet JSON.
    params["external_ids"] = {} if row.external_ids is None else row.external_ids
    return conn.execute(_UPSERT_SQL, params).one().id


class PgSourcePublicationQueries(SourcePublicationQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.normalize.source_publications.SourcePublicationQueries`."""

    def upsert_source_publication(self, conn: Connection, row: SourcePublicationRow) -> int:
        return upsert_source_publication(conn, row)
