"""Recherches vaines de la phase `fetch_missing` (table `failed_lookups`) : une ligne par identifiant cherché en vain dans une source, ou inconnu de doi.org (`DOI_ORG`).

Un identifiant inscrit sort des sélections le temps du délai de nouvelle tentative, et définitivement s'il est absent de son registre. Un document que la source renvoie efface l'échec. L'appelant commite.
"""

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import Connection, text

from domain.publications.identifiers import clean_doi
from domain.sources.registry import REGISTRY_LOOKUPS, Source

LookupIdType = Literal["doi", "hal_id", "nnt"]
"""Types d'identifiants cherchés par la phase `fetch_missing`, contraints par `failed_lookups_id_type_check`."""

_RECORD_SQL = text(
    """
    INSERT INTO failed_lookups (source, id_type, id_value, not_found_at)
    VALUES (CAST(:source AS lookup_source), :id_type, :id_value, now())
    ON CONFLICT (source, id_type, id_value) DO UPDATE SET not_found_at = EXCLUDED.not_found_at
    """
)


def record_failed_lookup(
    conn: Connection, source: str, id_type: LookupIdType, id_value: str
) -> None:
    """Inscrit, ou date de nouveau, l'échec de la recherche d'un identifiant dans une source.

    L'identifiant garde la forme que la sélection a fournie : la sélection le compare ensuite à cette forme.
    """
    conn.execute(_RECORD_SQL, {"source": source, "id_type": id_type, "id_value": id_value})


_FORGET_SQL = text(
    """
    DELETE FROM failed_lookups
    WHERE source = CAST(:source AS lookup_source) AND id_type = :id_type
      AND id_value = ANY(:values)
    """
)


def forget_failed_doi_lookups(conn: Connection, source: str, dois: Sequence[str | None]) -> None:
    """Efface les échecs inscrits dans la source pour ces DOI : DOI d'un document que la source renvoie, ou DOI que doi.org connaît (`DOI_ORG`).

    Les DOI passent par `clean_doi` : un document peut les donner sous toute forme.
    """
    cleaned = [clean for doi in dois if (clean := clean_doi(doi))]
    if cleaned:
        conn.execute(_FORGET_SQL, {"source": source, "id_type": "doi", "values": cleaned})


def forget_failed_hal_id_lookup(conn: Connection, hal_id: str) -> None:
    """Efface l'échec de la recherche d'un dépôt dans HAL, que HAL renvoie."""
    conn.execute(_FORGET_SQL, {"source": Source.HAL.value, "id_type": "hal_id", "values": [hal_id]})


def pending_failed_lookup_sql(*, source_sql: str, id_type: LookupIdType, value_sql: str) -> str:
    """Condition SQL vraie quand la recherche de l'identifiant dans la source a échoué il y a moins de `:retry_after_days` jours, ou à n'importe quelle date quand la source est le registre de ce type d'identifiant (`REGISTRY_LOOKUPS`).

    Source et identifiant sont des expressions SQL : paramètre lié, littéral ou colonne. Les sélections de la phase `fetch_missing` l'emploient sous `NOT`.
    """
    registries = sorted(str(source) for source, t in REGISTRY_LOOKUPS if t == id_type)
    definitive = (
        " OR fl.source::text IN (" + ", ".join(f"'{s}'" for s in registries) + ")"
        if registries
        else ""
    )
    return (
        "EXISTS (SELECT 1 FROM failed_lookups fl"
        f" WHERE fl.source = CAST(CAST({source_sql} AS text) AS lookup_source)"
        f" AND fl.id_type = '{id_type}'"
        f" AND fl.id_value = {value_sql}"
        f" AND (fl.not_found_at > now() - make_interval(days => :retry_after_days){definitive}))"
    )
