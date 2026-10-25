"""Fusion de deux revues : une étape SQL par donnée de la revue (`MERGE_STEPS`), puis la requalification des publications absorbées."""

from sqlalchemy import Connection, text

from domain.journals.journal import JournalType, ManualField
from domain.merge import DataNature, MergedEntity
from infrastructure.repositories.merge_steps import (
    MergeStep,
    fill_empty_unique,
    record_redirect,
    transfer,
    transfer_unique,
    untouched,
)
from pipeline.transformation.publications import lifecycle
from pipeline.transformation.publications.store import PublicationStore
from pipeline.transformation.publishing.journals.journal_publishers import (
    refresh_journal_publishers,
)
from pipeline.transformation.publishing.journals.requalify_journal import (
    correct_journal_records,
    requalify_journal_publications,
)
from pipeline.transformation.publishing.publication_counts import (
    refresh_journal_publication_count,
)


def _merge_issns(conn: Connection, target_id: int, source_id: int) -> None:
    """Un ISSN que la conservée a déjà reste le sien ; les autres passent à la conservée, à revérifier dans le Sudoc. L'ISSN de liaison de la conservée l'emporte. Des ISSN saisis à la main sur l'absorbée gardent leur marqueur."""
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

    return MergeStep(tuple(("journals", c) for c in columns), apply, DataNature.MIXED)


def _merge_is_in_doaj(conn: Connection, target_id: int, source_id: int) -> None:
    """La revue conservée est au DOAJ si l'une des deux y est."""
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
    "source_records": transfer("source_records", "journal_id"),
    "apc_payments": transfer("apc_payments", "journal_id"),
    "monographs": transfer("monographs", "journal_id"),
    "issns": MergeStep((("journal_issns", "journal_id"),), _merge_issns, DataNature.MIXED),
    "name_forms": transfer_unique(
        "journal_name_forms", "journal_id", "form_normalized", "publisher_id"
    ),
    "doi_namespaces": untouched("journal_doi_namespaces", "journal_id"),
    "title": untouched("journals", "title", "title_normalized").of_nature(DataNature.MIXED),
    "created_at": untouched("journals", "created_at"),
    # Éditeur calculé d'après les publications, recalculé après la fusion.
    "publisher": untouched("journals", "publisher_id"),
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
    "is_academic": untouched("journals", "is_academic").of_nature(DataNature.MIXED),
    "is_in_doaj": MergeStep((("journals", "is_in_doaj"),), _merge_is_in_doaj, DataNature.MIXED),
    "doaj_record": untouched("journals", "doaj_payload", "doaj_imported_at"),
    "publication_count": untouched("journals", "publication_count"),
    # Un champ repris de l'absorbée y apporte son marqueur (`_fill_empty_with_marker`).
    "manual_fields": untouched("journals", "manual_fields").of_nature(DataNature.DECISION),
}


def merge_journal_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime la revue absorbée et enregistre sa redirection, puis recalcule le nombre de publications et l'éditeur de la revue conservée."""
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    conn.execute(text("DELETE FROM journals WHERE id = :s"), {"s": source_id})
    record_redirect(conn, MergedEntity.JOURNAL, target_id, source_id)

    refresh_journal_publication_count(conn, target_id)
    refresh_journal_publishers(conn, target_id)


def merge_journals(conn: Connection, target_id: int, source_id: int) -> None:
    """Fusionne la revue `source_id` dans `target_id`, puis requalifie les publications absorbées contre le `journal_type` de la cible.

    Les corrections des `source_records` de la cible sont rejouées, absorbées comprises, puis les publications absorbées sont recalculées. Fusionner une revue dans un média donne à ses publications le type `media`.
    """
    store = PublicationStore(conn)
    absorbed_publication_ids = store.find_ids_by_journal_id(source_id)
    merge_journal_into(conn, target_id, source_id)
    correct_journal_records(conn, target_id)
    for publication_id in absorbed_publication_ids:
        lifecycle.refresh(conn, publication_id)


class JournalRecompute:
    """Recalculs ciblés d'une revue, exposés à l'API par `pipeline/public.py`."""

    def requalify_publications(self, conn: Connection, journal_id: int) -> int:
        """Requalifie les publications de la revue. Retourne le nombre de publications dont le `doc_type` change."""
        return requalify_journal_publications(conn, journal_id)

    def merge_journals(self, conn: Connection, target_id: int, source_id: int) -> None:
        """Fusionne la revue `source_id` dans `target_id` et requalifie les publications absorbées."""
        merge_journals(conn, target_id, source_id)
