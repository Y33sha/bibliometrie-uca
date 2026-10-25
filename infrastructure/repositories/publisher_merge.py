"""SQL de la fusion de deux éditeurs : une étape par donnée de l'éditeur (`MERGE_STEPS`).

Les revues homonymes des deux éditeurs sont fusionnées d'abord, par la fusion des revues."""

from sqlalchemy import Connection, text

from domain.merge import DataNature, MergedEntity
from domain.publishers.publisher import PublisherType
from infrastructure.repositories.merge_steps import (
    MergeStep,
    fill_empty,
    fill_empty_unique,
    record_redirect,
    transfer,
    transfer_unique,
    untouched,
)

MERGE_STEPS: dict[str, MergeStep] = {
    "serials": transfer("serials", "publisher_id"),
    "monographs": transfer("monographs", "publisher_id"),
    "source_records": transfer("source_records", "publisher_id"),
    "publications": transfer("publications", "publisher_id"),
    "apc_payments": transfer("apc_payments", "publisher_id"),
    "doi_prefixes": transfer("doi_prefixes", "publisher_id"),
    "name_forms": transfer("publisher_name_forms", "publisher_id"),
    # Formes de nom des revues rattachées à l'éditeur, une par forme.
    "serial_name_forms": transfer_unique("serial_name_forms", "publisher_id", "form_normalized"),
    "name": untouched("publishers", "name", "name_normalized").of_nature(DataNature.MIXED),
    "created_at": untouched("publishers", "created_at"),
    "openalex_id": fill_empty_unique("publishers", "openalex_id"),
    "country": fill_empty("publishers", "country").of_nature(DataNature.MIXED),
    "publisher_type": fill_empty(
        "publishers", "publisher_type", empty=PublisherType.UNKNOWN.value
    ).of_nature(DataNature.MIXED),
    "publication_count": untouched("publishers", "publication_count"),
}


def merge_publisher_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime l'éditeur absorbé et enregistre sa redirection."""
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    conn.execute(text("DELETE FROM publishers WHERE id = :s"), {"s": source_id})
    record_redirect(conn, MergedEntity.PUBLISHER, target_id, source_id)
