"""SQL de la fusion de deux éditeurs : une étape par donnée de `domain.publishers.merge.PUBLISHER_DATA`."""

from sqlalchemy import Connection, text

from domain.publishers.publisher import PublisherType
from infrastructure.repositories.merge_steps import (
    MergeStep,
    fill_empty,
    fill_empty_unique,
    transfer,
    transfer_unique,
    untouched,
)

MERGE_STEPS: dict[str, MergeStep] = {
    "journals": transfer("journals", "publisher_id"),
    "monographs": transfer("monographs", "publisher_id"),
    "apc_payments": transfer("apc_payments", "publisher_id"),
    "doi_prefixes": transfer("doi_prefixes", "publisher_id"),
    "name_forms": transfer("publisher_name_forms", "publisher_id"),
    "journal_name_forms": transfer_unique("journal_name_forms", "publisher_id", "form_normalized"),
    "name": untouched("publishers", "name", "name_normalized"),
    "created_at": untouched("publishers", "created_at"),
    "openalex_id": fill_empty_unique("publishers", "openalex_id"),
    "country": fill_empty("publishers", "country"),
    "publisher_type": fill_empty("publishers", "publisher_type", empty=PublisherType.UNKNOWN.value),
    "pub_count": untouched("publishers", "pub_count"),
}


def merge_publisher_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, puis supprime l'éditeur absorbé."""
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    conn.execute(text("DELETE FROM publishers WHERE id = :s"), {"s": source_id})
