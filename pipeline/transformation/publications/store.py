"""Persistance des publications : lecture, enregistrement, création, suppression."""

from collections.abc import Sequence

from sqlalchemy import Connection, RowMapping, bindparam, text

from domain.merge import MergedEntity
from domain.publications.dates import PublicationDate
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue_sql
from infrastructure.db.scalars import scalar_int
from infrastructure.repositories.merge_steps import record_redirect

_MARK_INSERTED = enqueue_sql(Queue.PUBLICATION_CONTRIBUTIONS, "SELECT id FROM inserted")

# Colonnes du lot écrit par `save` (`_save_payload`), lues par `jsonb_to_recordset`.
_SAVED = """jsonb_to_recordset(:payload) AS t(
    id integer, title text, title_normalized text, doc_type doc_type,
    publication_date date, publication_date_precision date_precision, doi text,
    oa_status oa_type, license license_type, deposit_license license_type, best_copy_url text,
    serial_id integer, monograph_id integer, publisher_id integer, container_title text,
    language text, is_retracted boolean, countries text[], source_extras jsonb, impact jsonb,
    corrections jsonb, abstract text, keywords text[], biblio jsonb
)"""

_RELEASE_CHANGED_DOIS_SQL = text(f"""
    UPDATE publications p SET doi = NULL, updated_at = now()
    FROM {_SAVED}
    WHERE p.id = t.id AND p.doi IS NOT NULL AND p.doi IS DISTINCT FROM t.doi
""").bindparams(bindparam("payload", type_=Jsonb))

_SAVE_CHANGED_SQL = text(f"""
    WITH computed AS (
        SELECT t.*,
               coalesce(t.publication_date, p.publication_date) AS kept_date,
               coalesce(t.publication_date_precision, p.publication_date_precision) AS kept_precision,
               coalesce(
                   (SELECT array_agg(DISTINCT sr.source ORDER BY sr.source)
                    FROM source_records sr WHERE sr.publication_id = t.id),
                   '{{}}'
               ) AS sources
        FROM {_SAVED}
        JOIN publications p ON p.id = t.id
    )
    UPDATE publications p SET
        title = c.title, title_normalized = c.title_normalized, doc_type = c.doc_type,
        publication_date = c.kept_date, publication_date_precision = c.kept_precision,
        doi = c.doi, oa_status = c.oa_status, license = c.license,
        deposit_license = c.deposit_license, best_copy_url = c.best_copy_url,
        serial_id = c.serial_id, monograph_id = c.monograph_id, publisher_id = c.publisher_id,
        container_title = c.container_title, language = c.language,
        is_retracted = c.is_retracted, countries = c.countries,
        source_extras = c.source_extras, impact = c.impact, corrections = c.corrections,
        sources = c.sources, subjects_ingested_at = NULL, updated_at = now()
    FROM computed c
    WHERE p.id = c.id
      AND (p.title, p.title_normalized, p.doc_type, p.publication_date,
           p.publication_date_precision, p.doi, p.oa_status, p.license, p.deposit_license,
           p.best_copy_url, p.serial_id, p.monograph_id, p.publisher_id, p.container_title,
           p.language, p.is_retracted, p.countries, p.source_extras, p.impact, p.corrections,
           p.sources)
          IS DISTINCT FROM
          (c.title, c.title_normalized, c.doc_type, c.kept_date,
           c.kept_precision, c.doi, c.oa_status, c.license, c.deposit_license,
           c.best_copy_url, c.serial_id, c.monograph_id, c.publisher_id, c.container_title,
           c.language, c.is_retracted, c.countries, c.source_extras, c.impact, c.corrections,
           c.sources)
""").bindparams(bindparam("payload", type_=Jsonb))

# Les colonnes volumineuses (résumé, mots-clés, biblio) vont dans `publications_detail`.
_SAVE_DETAIL_SQL = text(f"""
    INSERT INTO publications_detail (publication_id, abstract, keywords, biblio)
    SELECT t.id, t.abstract, t.keywords, t.biblio FROM {_SAVED}
    ON CONFLICT (publication_id) DO UPDATE SET
        abstract = EXCLUDED.abstract, keywords = EXCLUDED.keywords, biblio = EXCLUDED.biblio
    WHERE (publications_detail.abstract, publications_detail.keywords, publications_detail.biblio)
          IS DISTINCT FROM (EXCLUDED.abstract, EXCLUDED.keywords, EXCLUDED.biblio)
""").bindparams(bindparam("payload", type_=Jsonb))


class PublicationStore:
    """Lectures et écritures des publications."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_ids_by_serial_id(self, serial_id: int) -> list[int]:
        """Renvoie les publications de cette revue, à recalculer quand un champ modifiable de la revue change (`serial_type`)."""
        result = self._conn.execute(
            text("SELECT id FROM publications WHERE serial_id = :jid ORDER BY id"),
            {"jid": serial_id},
        )
        return [row.id for row in result]

    def find_doc_types_by_ids(self, publication_ids: list[int]) -> dict[int, str]:
        """Renvoie le `doc_type` de chaque publication demandée. Une publication supprimée, par un recalcul par exemple, est absente de la réponse."""
        if not publication_ids:
            return {}
        result = self._conn.execute(
            text(
                "SELECT id, CAST(doc_type AS text) AS doc_type FROM publications WHERE id = ANY(:ids)"
            ),
            {"ids": publication_ids},
        )
        return {row.id: row.doc_type for row in result}

    def find_by_id(self, publication_id: int) -> Publication | None:
        """Renvoie la publication de cet identifiant, sans ses contributions, ou `None`."""
        return self.find_by_ids([publication_id]).get(publication_id)

    def find_by_ids(self, publication_ids: Sequence[int]) -> dict[int, Publication]:
        """Renvoie les publications de ces identifiants, sans leurs contributions. Un identifiant inconnu est absent de la réponse."""
        rows = self._conn.execute(
            text("""
                SELECT p.id, p.title, p.title_normalized,
                       CAST(p.doc_type AS text) AS doc_type,
                       p.publication_year, p.publication_date,
                       CAST(p.publication_date_precision AS text) AS publication_date_precision,
                       p.doi,
                       CAST(p.oa_status AS text) AS oa_status,
                       CAST(p.license AS text) AS license,
                       CAST(p.deposit_license AS text) AS deposit_license,
                       p.best_copy_url, p.serial_id, p.monograph_id, p.publisher_id, p.container_title, p.language,
                       d.abstract, p.is_retracted, p.countries, d.keywords,
                       d.biblio, p.source_extras, p.impact, p.corrections
                FROM publications p
                LEFT JOIN publications_detail d ON d.publication_id = p.id
                WHERE p.id = ANY(:ids)
            """),
            {"ids": list(publication_ids)},
        )
        return {row.id: _publication_from_row(row._mapping) for row in rows}

    def save(self, publications: Sequence[Publication]) -> None:
        """Enregistre les champs modifiables de publications déjà insérées, et recalcule `sources` depuis leurs enregistrements sources.

        Seules les lignes dont une valeur change sont réécrites, avec leur date de mise à jour. Une date de publication absente garde la date en base. Toutes les publications reçues repassent à ingérer par la phase subjects (`subjects_ingested_at` vidé) : leurs enregistrements sources ont pu changer de sujets.
        """
        if not publications:
            return
        if any(p.id is None for p in publications):
            raise ValueError("save : chaque publication doit avoir un id (create pour insérer)")
        payload = [_save_payload(p) for p in publications]
        params = {"payload": payload}
        # Un index unique couvre le DOI, contrôlé ligne à ligne : un DOI qui passe d'une publication du lot à une autre est d'abord retiré de la première.
        self._conn.execute(_RELEASE_CHANGED_DOIS_SQL, params)
        self._conn.execute(_SAVE_CHANGED_SQL, params)
        self._conn.execute(_SAVE_DETAIL_SQL, params)
        self._conn.execute(
            text(
                "UPDATE publications SET subjects_ingested_at = NULL"
                " WHERE id = ANY(:ids) AND subjects_ingested_at IS NOT NULL"
            ),
            {"ids": [p.id for p in publications]},
        )

    def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        publication_year: int,
        doi: str | None,
        oa_status: str,
    ) -> int:
        """Insère une publication, sans dédoublonnage, la marque pour l'alignement des auteurs et renvoie son `id`. La date est à l'année `publication_year`. Les colonnes autres que les colonnes NOT NULL, la date et le DOI prennent leur valeur par défaut ; `save` les pose."""
        return scalar_int(
            self._conn.execute(
                text(f"""
                WITH inserted AS (
                    INSERT INTO publications
                        (title, title_normalized, doc_type, publication_date,
                         publication_date_precision, doi, oa_status)
                    VALUES (:title, :tn, CAST(:doc_type AS doc_type), :publication_date,
                            CAST(:publication_date_precision AS date_precision), :doi,
                            CAST(:oa AS oa_type))
                    RETURNING id
                ),
                marked AS ({_MARK_INSERTED})
                SELECT id FROM inserted
            """),
                {
                    "title": title,
                    "tn": title_normalized,
                    "doc_type": doc_type,
                    **_date_params(PublicationDate.of_year(publication_year)),
                    "doi": doi,
                    "oa": oa_status,
                },
            )
        )

    def has_source_records(self, publication_id: int) -> bool:
        """Vrai si au moins un enregistrement source est rattaché à la publication."""
        return bool(
            self._conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM source_records WHERE publication_id = :id)"),
                {"id": publication_id},
            ).scalar_one()
        )

    def repoint_dependents(self, from_publication_id: int, to_publication_id: int) -> None:
        """Rattache les paiements APC (`apc_payments`) de `from_publication_id` à `to_publication_id`, et enregistre la redirection de son identifiant."""
        self._conn.execute(
            text("UPDATE apc_payments SET publication_id = :t WHERE publication_id = :s"),
            {"s": from_publication_id, "t": to_publication_id},
        )
        record_redirect(
            self._conn, MergedEntity.PUBLICATION, to_publication_id, from_publication_id
        )

    def delete(self, publication_ids: Sequence[int]) -> None:
        """Supprime des publications, avec leurs `contributions` et leurs `publication_subjects`. `apc_payments.publication_id` et `source_records.publication_id` passent à NULL."""
        if not publication_ids:
            return
        self._conn.execute(
            text("DELETE FROM publications WHERE id = ANY(:ids)"),
            {"ids": list(publication_ids)},
        )


def _date_params(publication_date: PublicationDate | None) -> dict[str, object]:
    """Renvoie les paramètres de la date de publication et de sa précision. La base en tire `publication_year`."""
    if publication_date is None:
        return {"publication_date": None, "publication_date_precision": None}
    return {
        "publication_date": publication_date.value,
        "publication_date_precision": publication_date.precision.value,
    }


def _publication_from_row(m: RowMapping) -> Publication:
    """Construit la publication d'une ligne lue par `find_by_ids`."""
    return Publication(
        id=m["id"],
        title=m["title"],
        publication_year=m["publication_year"],
        publication_date=PublicationDate.stored(
            m["publication_date"], m["publication_date_precision"]
        ),
        title_normalized=m["title_normalized"],
        doc_type=m["doc_type"],
        doi=DOI(m["doi"]) if m["doi"] else None,
        oa_status=m["oa_status"],
        license=m["license"],
        deposit_license=m["deposit_license"],
        best_copy_url=m["best_copy_url"],
        serial_id=m["serial_id"],
        monograph_id=m["monograph_id"],
        publisher_id=m["publisher_id"],
        container_title=m["container_title"],
        language=m["language"],
        abstract=m["abstract"],
        is_retracted=m["is_retracted"],
        countries=tuple(m["countries"]) if m["countries"] else (),
        keywords=tuple(m["keywords"]) if m["keywords"] else (),
        biblio=m["biblio"],
        source_extras=m["source_extras"],
        impact=m["impact"],
        corrections=m["corrections"],
    )


def _save_payload(publication: Publication) -> dict[str, JsonValue]:
    """Renvoie la ligne du lot écrit par `save` pour une publication. Un tuple vide s'écrit NULL."""
    date = publication.publication_date
    return {
        "id": publication.id,
        "title": publication.title,
        "title_normalized": publication.title_normalized,
        "doc_type": publication.doc_type,
        "publication_date": date.value.isoformat() if date else None,
        "publication_date_precision": date.precision.value if date else None,
        "doi": str(publication.doi) if publication.doi else None,
        "oa_status": publication.oa_status,
        "license": publication.license,
        "deposit_license": publication.deposit_license,
        "best_copy_url": publication.best_copy_url,
        "serial_id": publication.serial_id,
        "monograph_id": publication.monograph_id,
        "publisher_id": publication.publisher_id,
        "container_title": publication.container_title,
        "language": publication.language,
        "is_retracted": publication.is_retracted,
        "countries": list(publication.countries) if publication.countries else None,
        "source_extras": publication.source_extras,
        "impact": publication.impact,
        "corrections": publication.corrections,
        "abstract": publication.abstract,
        "keywords": list(publication.keywords) if publication.keywords else None,
        "biblio": publication.biblio,
    }
