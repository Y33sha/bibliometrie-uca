"""Fusion de deux revues : une étape SQL par donnée de la revue (`MERGE_STEPS`), puis la requalification des publications absorbées."""

from sqlalchemy import Connection, text

from domain.merge import DataNature, MergedEntity
from domain.serials.serial import ManualField, SerialType
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
from pipeline.transformation.publishing.publication_counts import (
    refresh_serial_publication_count,
)
from pipeline.transformation.publishing.serials.requalify_serial import (
    correct_serial_records,
    requalify_serial_publications,
)
from pipeline.transformation.publishing.serials.serial_publishers import (
    refresh_serial_publishers,
)


def _merge_issns(conn: Connection, target_id: int, source_id: int) -> None:
    """Transfère à la revue conservée les ISSN de l'absorbée absents chez elle, à revérifier dans le Sudoc. L'ISSN de liaison de la conservée l'emporte. Des ISSN saisis à la main sur l'absorbée gardent leur marqueur."""
    conn.execute(
        text("""
            DELETE FROM serial_issns s
            WHERE s.serial_id = :s
              AND EXISTS (SELECT 1 FROM serial_issns t WHERE t.serial_id = :t AND t.issn = s.issn)
        """),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("""
            UPDATE serial_issns
            SET serial_id = :t, sudoc_checked_at = NULL,
                linking = linking AND NOT EXISTS (
                    SELECT 1 FROM serial_issns WHERE serial_id = :t AND linking
                )
            WHERE serial_id = :s
        """),
        {"t": target_id, "s": source_id},
    )
    # Des ISSN saisis à la main sur l'absorbée gardent leur autorité sur la liste réunie.
    conn.execute(
        text("""
            UPDATE serials t SET manual_fields = t.manual_fields || CAST(:field AS text)
            FROM serials s
            WHERE t.id = :t AND s.id = :s
              AND :field = ANY(s.manual_fields) AND NOT :field = ANY(t.manual_fields)
        """),
        {"t": target_id, "s": source_id, "field": ManualField.ISSNS.value},
    )


def _fill_empty_with_marker(
    field: ManualField, columns: tuple[str, ...], is_empty: str
) -> MergeStep:
    """Renvoie l'étape qui remplit les colonnes vides de la revue conservée, prises ensemble. Une valeur reprise de l'absorbée garde son marqueur de saisie à la main.

    Args:
        is_empty: condition SQL de vide sur la revue conservée `t`.
    """
    assignments = ", ".join(f"{c} = s.{c}" for c in columns)

    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"""
                UPDATE serials t
                SET {assignments},
                    manual_fields = CASE
                        WHEN :field = ANY(s.manual_fields) AND NOT :field = ANY(t.manual_fields)
                        THEN t.manual_fields || CAST(:field AS text)
                        ELSE t.manual_fields
                    END
                FROM serials s
                WHERE t.id = :t AND s.id = :s AND {is_empty}
            """),
            {"t": target_id, "s": source_id, "field": field.value},
        )

    return MergeStep(tuple(("serials", c) for c in columns), apply, DataNature.MIXED)


def _merge_is_in_doaj(conn: Connection, target_id: int, source_id: int) -> None:
    """Marque la revue conservée présente au DOAJ si l'une des deux l'est."""
    conn.execute(
        text("""
            UPDATE serials t SET is_in_doaj = COALESCE(t.is_in_doaj OR s.is_in_doaj, false)
            FROM serials s
            WHERE t.id = :t AND s.id = :s
        """),
        {"t": target_id, "s": source_id},
    )


MERGE_STEPS: dict[str, MergeStep] = {
    "publications": transfer("publications", "serial_id"),
    "source_records": transfer("source_records", "serial_id"),
    "apc_payments": transfer("apc_payments", "serial_id"),
    "monographs": transfer("monographs", "serial_id"),
    "issns": MergeStep((("serial_issns", "serial_id"),), _merge_issns, DataNature.MIXED),
    "name_forms": transfer_unique(
        "serial_name_forms", "serial_id", "form_normalized", "publisher_id"
    ),
    "doi_namespaces": untouched("serial_doi_namespaces", "serial_id"),
    "title": untouched("serials", "title", "title_normalized").of_nature(DataNature.MIXED),
    "created_at": untouched("serials", "created_at"),
    # Éditeur calculé d'après les publications, recalculé après la fusion.
    "publisher": untouched("serials", "publisher_id"),
    "openalex_id": fill_empty_unique("serials", "openalex_id"),
    "oa_model": _fill_empty_with_marker(ManualField.OA_MODEL, ("oa_model",), "t.oa_model IS NULL"),
    "serial_type": _fill_empty_with_marker(
        ManualField.SERIAL_TYPE,
        ("serial_type",),
        f"t.serial_type = '{SerialType.UNKNOWN.value}'",
    ),
    "is_academic": untouched("serials", "is_academic").of_nature(DataNature.MIXED),
    "is_in_doaj": MergeStep((("serials", "is_in_doaj"),), _merge_is_in_doaj, DataNature.MIXED),
    "doaj_record": untouched("serials", "doaj_payload", "doaj_imported_at"),
    "publication_count": untouched("serials", "publication_count"),
    # Un champ repris de l'absorbée ajoute son marqueur à `manual_fields` (`_fill_empty_with_marker`).
    "manual_fields": untouched("serials", "manual_fields").of_nature(DataNature.DECISION),
}


def merge_serial_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime la revue absorbée et enregistre sa redirection, puis recalcule le nombre de publications et l'éditeur de la revue conservée."""
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    conn.execute(text("DELETE FROM serials WHERE id = :s"), {"s": source_id})
    record_redirect(conn, MergedEntity.SERIAL, target_id, source_id)

    refresh_serial_publication_count(conn, target_id)
    refresh_serial_publishers(conn, target_id)


def merge_serials(conn: Connection, target_id: int, source_id: int) -> None:
    """Fusionne la revue `source_id` dans `target_id`, puis requalifie les publications absorbées selon le `serial_type` de la cible.

    Les corrections des enregistrements sources de la cible sont rejouées, absorbées comprises, puis les publications absorbées sont recalculées. Fusionner une revue dans un média donne à ses publications le type `media`.
    """
    store = PublicationStore(conn)
    absorbed_publication_ids = store.find_ids_by_serial_id(source_id)
    merge_serial_into(conn, target_id, source_id)
    correct_serial_records(conn, target_id)
    for publication_id in absorbed_publication_ids:
        lifecycle.refresh(conn, publication_id)


class SerialRecompute:
    """Recalculs ciblés d'une revue, exposés à l'API par `pipeline/public.py`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def requalify_publications(self, serial_id: int) -> int:
        """Requalifie les publications de la revue. Renvoie le nombre de publications dont le `doc_type` change."""
        return requalify_serial_publications(self._conn, serial_id)

    def merge_serials(self, target_id: int, source_id: int) -> None:
        """Fusionne la revue `source_id` dans `target_id` et requalifie les publications absorbées."""
        merge_serials(self._conn, target_id, source_id)
