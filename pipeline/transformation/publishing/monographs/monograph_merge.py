"""Fusion de deux monographies : une étape SQL par donnée de la monographie (`MERGE_STEPS`)."""

from sqlalchemy import Connection, text

from domain.merge import MergedEntity
from infrastructure.repositories.merge_steps import (
    MergeStep,
    fill_empty,
    record_redirect,
    transfer,
    untouched,
)
from pipeline.transformation.publishing.monographs.store import MonographStore


def _merge_proceedings(conn: Connection, target_id: int, source_id: int) -> None:
    """La monographie conservée est un volume d'actes si l'une des deux l'est."""
    conn.execute(
        text("""
            UPDATE monographs t SET proceedings = t.proceedings OR s.proceedings
            FROM monographs s
            WHERE t.id = :t AND s.id = :s
        """),
        {"t": target_id, "s": source_id},
    )


def _merge_isbns(conn: Connection, target_id: int, source_id: int) -> None:
    """La conservée reçoit les ISBN de l'absorbée qui lui manquent, sauf ceux qu'une autre monographie a déjà. L'absorbée les libère d'abord : la contrainte d'unicité le demande."""
    source = conn.execute(
        text("SELECT isbn, eisbn FROM monographs WHERE id = :s"), {"s": source_id}
    ).one()
    conn.execute(
        text("UPDATE monographs SET isbn = NULL, eisbn = NULL WHERE id = :s"), {"s": source_id}
    )
    MonographStore(conn).enrich_monograph(
        target_id,
        proceedings=False,
        year=None,
        isbn=source.isbn,
        eisbn=source.eisbn,
        publisher_id=None,
        serial_id=None,
    )


MERGE_STEPS: dict[str, MergeStep] = {
    "source_records": transfer("source_records", "monograph_id"),
    "publications": transfer("publications", "monograph_id"),
    "title": untouched("monographs", "title", "title_normalized"),
    "created_at": untouched("monographs", "created_at"),
    "proceedings": MergeStep((("monographs", "proceedings"),), _merge_proceedings),
    "year": fill_empty("monographs", "year"),
    "isbns": MergeStep((("monographs", "isbn"), ("monographs", "eisbn")), _merge_isbns),
    "publisher": fill_empty("monographs", "publisher_id"),
    "serial": fill_empty("monographs", "serial_id"),
}


def merge_monograph_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime la monographie absorbée et enregistre sa redirection."""
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    conn.execute(text("DELETE FROM monographs WHERE id = :s"), {"s": source_id})
    record_redirect(conn, MergedEntity.MONOGRAPH, target_id, source_id)
