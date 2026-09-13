"""Journal des recherches infructueuses de la phase `fetch_missing` (table `failed_lookups`).

Une ligne par identifiant cherché en vain dans une source. `record_failed_lookup` inscrit l'échec, `forget_failed_doi_lookups` efface les échecs démentis par un document reçu, `pending_failed_lookup_sql` écarte des sélections les identifiants en attente. Le commit est à la charge de l'appelant.
"""

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Connection, text

from domain.publications.identifiers import clean_doi
from domain.sources.registry import is_native_identifier

LookupIdType = Literal["doi", "hal_id", "nnt"]
"""Types d'identifiants cherchés par la phase `fetch_missing`, contraints par `failed_lookups_id_type_check`."""

_RECORD_SQL = text(
    """
    INSERT INTO failed_lookups (source, id_type, id_value, not_found_at, next_retry)
    VALUES (
        CAST(:source AS source_type), :id_type, :id_value, now(),
        CASE WHEN :permanent THEN NULL ELSE now() + make_interval(days => :days) END
    )
    ON CONFLICT (source, id_type, id_value) DO UPDATE SET
        not_found_at = EXCLUDED.not_found_at,
        next_retry = EXCLUDED.next_retry
    """
)


def record_failed_lookup(
    conn: Connection, source: str, id_type: LookupIdType, id_value: str, *, retry_after_days: int
) -> None:
    """Inscrit, ou réarme, l'échec de la recherche de `id_value` dans `source`.

    L'échec est définitif (`next_retry` NULL) quand `id_type` est l'identifiant natif de `source`. Sinon, la recherche reprend après `retry_after_days` jours : la source peut indexer le document plus tard.

    `id_value` est la valeur cherchée, telle que la sélection l'a fournie : la sélection la compare ensuite à cette même forme. Ne commit pas.
    """
    conn.execute(
        _RECORD_SQL,
        {
            "source": source,
            "id_type": id_type,
            "id_value": id_value,
            "permanent": is_native_identifier(source, id_type),
            "days": retry_after_days,
        },
    )


_FORGET_DOIS_SQL = text(
    """
    DELETE FROM failed_lookups
    WHERE source = CAST(:source AS source_type) AND id_type = 'doi' AND id_value = ANY(:dois)
    """
)


def forget_failed_doi_lookups(conn: Connection, source: str, dois: Sequence[str | None]) -> None:
    """Efface les échecs inscrits dans `source` pour les DOI d'un document qu'elle rend.

    Un document reçu porte ses identifiants : la source les connaît, qu'il entre en base ou qu'il y soit déjà. Les DOI passent par `clean_doi`, le document pouvant les exposer sous toute forme. Ne commit pas.
    """
    propres = [propre for doi in dois if (propre := clean_doi(doi))]
    if propres:
        conn.execute(_FORGET_DOIS_SQL, {"source": source, "dois": propres})


def pending_failed_lookup_sql(*, source_sql: str, id_type: LookupIdType, value_sql: str) -> str:
    """Condition SQL vraie quand la recherche de `value_sql` dans `source_sql` a échoué et attend encore sa reprise.

    `source_sql` et `value_sql` sont des expressions SQL : paramètre lié, littéral ou colonne. Les sélections de la phase `fetch_missing` l'emploient sous `NOT` pour écarter ces identifiants.
    """
    return (
        "EXISTS (SELECT 1 FROM failed_lookups fl"
        f" WHERE fl.source = {source_sql} AND fl.id_type = '{id_type}'"
        f" AND fl.id_value = {value_sql}"
        " AND (fl.next_retry IS NULL OR fl.next_retry > now()))"
    )
