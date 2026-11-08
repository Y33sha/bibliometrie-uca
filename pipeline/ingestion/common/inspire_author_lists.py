"""Enregistrements sources OpenAlex sans contributions sources, à la place desquelles valent celles d'INSPIRE-HEP (`domain.source_records.inspire_author_lists`).

La normalisation d'OpenAlex écrit sans contributions sources un enregistrement source du même document qu'un enregistrement source INSPIRE-HEP (`fetch_author_list_keys`). Après la normalisation des sources, `withhold_covered_source_contributions` retire leurs contributions sources aux enregistrements sources OpenAlex normalisés avant l'arrivée de l'enregistrement source INSPIRE-HEP.
"""

import logging
from itertools import batched

from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifierRole, SourceIdentifierType
from domain.source_records.inspire_author_lists import (
    AUTHOR_LIST_SOURCE,
    DOCUMENT_IDENTIFIER_TYPES,
    WITHHELD_AUTHORS_SOURCE,
    DocumentKey,
)
from infrastructure.sql_fragments import in_clause
from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
from pipeline.runtime.observability.log_format import BRANCH
from pipeline.runtime.observability.progress import track_progress


def _document_identifier(identifier: str) -> str:
    """Renvoie la condition SQL : l'identifiant `identifier` est d'un type de `DOCUMENT_IDENTIFIER_TYPES`, de rôle autre que `related`."""
    return (
        f"{identifier}.id_type::text IN {in_clause(DOCUMENT_IDENTIFIER_TYPES)}"
        f" AND {identifier}.role <> '{SourceIdentifierRole.RELATED}'"
    )


_AUTHOR_LIST_KEYS_SQL = text(f"""
    SELECT DISTINCT i.id_type::text AS id_type, i.id_value
    FROM source_record_identifiers i
    JOIN source_records sr ON sr.id = i.source_record_id
    WHERE sr.source = '{AUTHOR_LIST_SOURCE}' AND {_document_identifier("i")}
""")

_COVERED_SQL = text(f"""
    SELECT DISTINCT sr.id
    FROM source_records sr
    JOIN source_record_identifiers o ON o.source_record_id = sr.id
    JOIN source_record_identifiers a ON a.id_type = o.id_type AND a.id_value = o.id_value
    JOIN source_records asr ON asr.id = a.source_record_id
    WHERE sr.source = '{WITHHELD_AUTHORS_SOURCE}' AND asr.source = '{AUTHOR_LIST_SOURCE}'
      AND {_document_identifier("o")} AND {_document_identifier("a")}
      AND (
          sr.authors_hash IS NOT NULL
          OR EXISTS (SELECT 1 FROM source_contributions sc WHERE sc.source_record_id = sr.id)
      )
    ORDER BY sr.id
""")
"""Enregistrements sources OpenAlex du même document qu'un enregistrement source INSPIRE-HEP, avec des contributions sources ou une empreinte de bloc auteurs."""

_WITHHOLD_BATCH = 200
"""Enregistrements sources OpenAlex par suppression. Un enregistrement de physique des hautes énergies compte souvent plus de mille contributions sources."""


def fetch_author_list_keys(conn: Connection) -> frozenset[DocumentKey]:
    """Renvoie les identifiants des enregistrements sources INSPIRE-HEP qui désignent leur document (`document_keys`)."""
    return frozenset(
        (SourceIdentifierType(r.id_type), r.id_value) for r in conn.execute(_AUTHOR_LIST_KEYS_SQL)
    )


def withhold_covered_source_contributions(conn: Connection, logger: logging.Logger) -> int:
    """Supprime les contributions sources des enregistrements sources OpenAlex du même document qu'un enregistrement source INSPIRE-HEP, et renvoie leur nombre.

    Chaque lot de `_WITHHOLD_BATCH` enregistrements sources est commité : une interruption garde les lots traités. Une barre d'avancement compte les enregistrements sources.
    """
    covered = list(conn.execute(_COVERED_SQL).scalars())
    if not covered:
        return 0
    store = SourceContributionStore(conn)
    withheld = 0
    with track_progress(
        len(covered), f"{BRANCH}enregistrements sources OpenAlex", logger, erase=True
    ) as progress:
        for ids in batched(covered, _WITHHOLD_BATCH, strict=False):
            withheld += store.withhold_source_contributions(list(ids))
            conn.commit()
            progress.advance(len(ids))
    return withheld
