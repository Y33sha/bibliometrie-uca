"""SQL de la fusion de deux revues : une étape par donnée de `domain.journals.merge.JOURNAL_DATA`."""

from sqlalchemy import Connection, text

from domain.journals.journal import JournalType, ManualField
from infrastructure.pipeline.authorships.pub_counts import (
    refresh_journal_pub_count,
    refresh_publisher_pub_count,
)
from infrastructure.repositories.merge_steps import (
    MergeStep,
    fill_empty,
    fill_empty_unique,
    transfer,
    transfer_unique,
    untouched,
)


def _merge_issns(conn: Connection, target_id: int, source_id: int) -> None:
    conn.execute(
        text("""
            DELETE FROM journal_issns s
            WHERE s.journal_id = :s
              AND EXISTS (SELECT 1 FROM journal_issns t WHERE t.journal_id = :t AND t.issn = s.issn)
        """),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("""
            UPDATE journal_issns
            SET journal_id = :t, sudoc_checked_at = NULL,
                linking = linking AND NOT EXISTS (
                    SELECT 1 FROM journal_issns WHERE journal_id = :t AND linking
                )
            WHERE journal_id = :s
        """),
        {"t": target_id, "s": source_id},
    )
    # Des ISSN saisis à la main sur l'absorbée gardent leur autorité sur la liste réunie.
    conn.execute(
        text("""
            UPDATE journals t SET manual_fields = t.manual_fields || CAST(:field AS text)
            FROM journals s
            WHERE t.id = :t AND s.id = :s
              AND :field = ANY(s.manual_fields) AND NOT :field = ANY(t.manual_fields)
        """),
        {"t": target_id, "s": source_id, "field": ManualField.ISSNS.value},
    )


def _fill_empty_with_marker(
    field: ManualField, columns: tuple[str, ...], is_empty: str
) -> MergeStep:
    """Remplir si vide, les colonnes prises ensemble ; `is_empty` est la condition SQL de vide sur la revue conservée `t`. Une valeur reprise de l'absorbée garde son marqueur de saisie à la main."""
    assignments = ", ".join(f"{c} = s.{c}" for c in columns)

    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"""
                UPDATE journals t
                SET {assignments},
                    manual_fields = CASE
                        WHEN :field = ANY(s.manual_fields) AND NOT :field = ANY(t.manual_fields)
                        THEN t.manual_fields || CAST(:field AS text)
                        ELSE t.manual_fields
                    END
                FROM journals s
                WHERE t.id = :t AND s.id = :s AND {is_empty}
            """),
            {"t": target_id, "s": source_id, "field": field.value},
        )

    return MergeStep(tuple(("journals", c) for c in columns), apply)


def _merge_is_in_doaj(conn: Connection, target_id: int, source_id: int) -> None:
    conn.execute(
        text("""
            UPDATE journals t SET is_in_doaj = COALESCE(t.is_in_doaj OR s.is_in_doaj, false)
            FROM journals s
            WHERE t.id = :t AND s.id = :s
        """),
        {"t": target_id, "s": source_id},
    )


MERGE_STEPS: dict[str, MergeStep] = {
    "publications": transfer("publications", "journal_id"),
    "source_publications": transfer("source_publications", "journal_id"),
    "apc_payments": transfer("apc_payments", "journal_id"),
    "monographs": transfer("monographs", "journal_id"),
    "issns": MergeStep((("journal_issns", "journal_id"),), _merge_issns),
    "name_forms": transfer_unique(
        "journal_name_forms", "journal_id", "form_normalized", "publisher_id"
    ),
    "doi_namespaces": untouched("journal_doi_namespaces", "journal_id"),
    "title": untouched("journals", "title", "title_normalized"),
    "created_at": untouched("journals", "created_at"),
    "publisher": fill_empty("journals", "publisher_id"),
    "openalex_id": fill_empty_unique("journals", "openalex_id"),
    "oa_model": _fill_empty_with_marker(ManualField.OA_MODEL, ("oa_model",), "t.oa_model IS NULL"),
    "apc": _fill_empty_with_marker(
        ManualField.APC, ("apc_amount", "apc_currency"), "t.apc_amount IS NULL"
    ),
    "journal_type": _fill_empty_with_marker(
        ManualField.JOURNAL_TYPE,
        ("journal_type",),
        f"t.journal_type = '{JournalType.UNKNOWN.value}'",
    ),
    "is_academic": untouched("journals", "is_academic"),
    "is_in_doaj": MergeStep((("journals", "is_in_doaj"),), _merge_is_in_doaj),
    "doaj_record": untouched("journals", "doaj_payload", "doaj_imported_at"),
    "pub_count": untouched("journals", "pub_count"),
    # Un champ repris de l'absorbée y apporte son marqueur (`_fill_empty_with_marker`).
    "manual_fields": untouched("journals", "manual_fields"),
}


def merge_journal_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime la revue absorbée, puis recalcule les nombres de publications de la revue conservée et des éditeurs concernés."""
    source_publisher_id = conn.execute(
        text("SELECT publisher_id FROM journals WHERE id = :s"), {"s": source_id}
    ).scalar()
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    conn.execute(text("DELETE FROM journals WHERE id = :s"), {"s": source_id})

    refresh_journal_pub_count(conn, target_id)
    target_publisher_id = conn.execute(
        text("SELECT publisher_id FROM journals WHERE id = :t"), {"t": target_id}
    ).scalar()
    for publisher_id in {target_publisher_id, source_publisher_id}:
        if publisher_id is not None:
            refresh_publisher_pub_count(conn, publisher_id)
