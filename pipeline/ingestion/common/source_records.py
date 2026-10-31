"""Écriture et suppression des enregistrements sources, communes aux normaliseurs de toutes les sources.

Un enregistrement source est la vue normalisée du dernier import, qui fait autorité : l'écriture réécrit toutes les colonnes renseignées par l'import. La clé `(source, source_id)` garde l'`id` de la ligne d'un import à l'autre, pour les tables qui la référencent.

Les colonnes absentes de l'import restent en l'état : le rattachement à la publication, recalculé par la phase `publications` pour chaque enregistrement source écrit ; les pays, calculés par la phase `countries` ; la date de création.
"""

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields

from sqlalchemy import Connection, bindparam, text

from domain.normalize import clean_abstract, drop_duplicate_mathml, strip_abstract_label
from domain.publications.dates import PublicationDate
from domain.publications.doc_types import DocType
from domain.publications.licenses import License
from domain.publications.metadata import clean_publication_title, normalized_title
from domain.publishers.attribution import source_record_has_publisher
from domain.serials.titles import names_ebook_platform
from domain.source_records.doc_types import map_doc_type
from domain.source_records.identifiers import SourceIdentifier, normalize_identifiers
from domain.source_records.languages import language_code
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue, enqueue_sql
from infrastructure.db.scalars import scalar_int

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRecordUpsert:
    """Un enregistrement source fourni par une source, prêt à être écrit.

    Le jeu de colonnes est commun à toutes les sources ; une colonne non renseignée par la source reste à `None`. Les absences suivent les données exposées par chaque source : theses.fr est sans résumé, HAL et theses.fr sans indicateur de citation ; `hal_collections` existe seulement pour HAL, `is_retracted` seulement pour OpenAlex.

    `title` et `abstract` sont nettoyés à l'écriture (`clean_publication_title`, `clean_abstract`), et `title_normalized` se dérive du titre. `doc_type` de `raw_doc_type` (`map_doc_type`) et `language` de `raw_language` (`language_code`). `publication_id`, rattachement à la publication, est posé par la phase `publications`.
    """

    # Clé de l'enregistrement source
    source: str
    source_id: str
    """Identifiant natif de la source : hal-id, id OpenAlex, UT WoS, id ScanR, id theses.fr ou NNT, DOI pour crossref et datacite."""
    staging_id: int

    # Rattachement
    identifiers: tuple[SourceIdentifier, ...] = ()
    """Identifiants de l'enregistrement source, avec leur rôle, écrits dans `source_record_identifiers`. L'écriture les normalise."""

    # Métadonnées bibliographiques
    title: str
    publication_date: PublicationDate | None = None
    """Date de publication, avec sa précision. La base en tire `publication_year`."""
    raw_doc_type: str | None = None
    """Type de document dans le vocabulaire de la source."""
    monograph_id: int | None = None
    publisher_id: int | None = None
    """Éditeur nommé par la source. L'écriture le retire d'une production hébergée sans être publiée (`source_record_has_publisher`)."""
    container_title: str | None = None
    """Titre libre du conteneur. L'écriture retire un titre de plateforme d'ebooks (`names_ebook_platform`)."""
    raw_language: str | None = None
    """Langue dans le vocabulaire de la source."""
    biblio: JsonValue = None

    # Contenu
    abstract: str | None = None
    """Résumé. L'écriture retire la version MathML d'une formule déposée aussi en LaTeX (`drop_duplicate_mathml`) et l'intitulé « Abstract » ou « Résumé » en tête (`strip_abstract_label`)."""
    keywords: list[str] | None = None
    topics: JsonValue = None

    # Open access
    license: License | None = None
    urls: list[str] | None = None

    # Citations et drapeaux
    impact: JsonValue = None
    """Indicateurs de citation, construits par `domain.source_records.impact.Impact.to_json`."""
    is_retracted: bool | None = None

    # Collections HAL
    hal_collections: list[str] | None = None

    # Charge utile propre à la source
    source_extras: JsonValue = None


_FIELDS = tuple(
    f for f in fields(SourceRecordUpsert) if f.name not in ("identifiers", "publication_date")
)

# Les colonnes écrites se dérivent des champs de la ligne, plus les colonnes calculées à l'écriture : un champ ajouté à `SourceRecordUpsert` s'écrit sans autre geste.
_ROW_FIELDS = tuple(f.name for f in _FIELDS)
_DATE_COLUMNS = ("publication_date", "publication_date_precision")
_COLUMNS = (*_ROW_FIELDS, "title_normalized", "doc_type", "language", *_DATE_COLUMNS)

# Tout est réécrit, sauf la clé de conflit. `corrections` se vide : ses valeurs d'origine viennent de l'import précédent, et la phase `metadata_correction` refait ses corrections sur les valeurs fraîches.
_UPDATED_COLUMNS = tuple(c for c in _COLUMNS if c not in ("source", "source_id"))

# Colonnes JSONB : les champs annotés `JsonValue` ; les `list[str]` sont des `text[]`. Un champ JSONB ajouté au contrat est typé sans autre geste.
_JSONB_COLUMNS = tuple(f.name for f in _FIELDS if f.type is JsonValue)

# Colonnes à type énuméré PostgreSQL : le paramètre est converti vers ce type.
_ENUM_CASTS = {
    "doc_type": "doc_type",
    "license": "license_type",
    "publication_date_precision": "date_precision",
}


def _value(column: str) -> str:
    cast = _ENUM_CASTS.get(column)
    return f"CAST(:{column} AS {cast})" if cast else f":{column}"


# Chaque écriture marque l'enregistrement source pour la réconciliation.
_UPSERT_SQL = text(
    f"""
    WITH upserted AS (
        INSERT INTO source_records ({", ".join(_COLUMNS)})
        VALUES ({", ".join(_value(c) for c in _COLUMNS)})
        ON CONFLICT (source, source_id) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATED_COLUMNS)},
            corrections = '{{}}'::jsonb,
            updated_at = clock_timestamp()
        RETURNING id
    ),
    marked AS ({enqueue_sql(Queue.SOURCE_RECORD_KEYS, "SELECT id FROM upserted")})
    SELECT id FROM upserted
    """  # noqa: S608 — listes de colonnes construites depuis le contrat, sans entrée externe
).bindparams(*(bindparam(c, type_=Jsonb) for c in _JSONB_COLUMNS))


_DELETE_IDENTIFIERS = text(
    "DELETE FROM source_record_identifiers WHERE source_record_id = ANY(:source_record_ids)"
)

_INSERT_IDENTIFIERS = text("""
    INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role)
    SELECT i.source_record_id, CAST(i.id_type AS source_identifier_type), i.id_value,
           CAST(i.role AS source_identifier_role)
    FROM jsonb_to_recordset(CAST(:identifiers AS jsonb))
        AS i(source_record_id integer, id_type text, id_value text, role text)
""")


def replace_identifiers(
    conn: Connection, identifiers_by_source_record: Mapping[int, Iterable[SourceIdentifier]]
) -> None:
    """Réécrit les identifiants des enregistrements sources donnés, en une suppression et une insertion. Chaque identifiant écrit est actif."""
    conn.execute(_DELETE_IDENTIFIERS, {"source_record_ids": list(identifiers_by_source_record)})
    rows = [
        {
            "source_record_id": source_record_id,
            "id_type": i.id_type.value,
            "id_value": i.value,
            "role": i.role.value,
        }
        for source_record_id, identifiers in identifiers_by_source_record.items()
        for i in identifiers
    ]
    if rows:
        conn.execute(_INSERT_IDENTIFIERS, {"identifiers": json.dumps(rows)})


def date_columns(publication_date: PublicationDate | None) -> dict[str, object]:
    """Renvoie les colonnes de la date de publication et de sa précision."""
    if publication_date is None:
        return dict.fromkeys(_DATE_COLUMNS)
    return {
        "publication_date": publication_date.value,
        "publication_date_precision": publication_date.precision.value,
    }


def stored_abstract(abstract: str | None) -> str | None:
    """Renvoie le résumé tel qu'il est écrit : nettoyé, sans copie MathML d'une formule TeX ni intitulé de tête (« Abstract »)."""
    return strip_abstract_label(drop_duplicate_mathml(clean_abstract(abstract)))


class SourceRecordStore:
    """Écriture des enregistrements sources et de leurs identifiants. Les formes de langue se chargent à la première écriture."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._language_forms: dict[str, str] | None = None

    def upsert_source_record(self, row: SourceRecordUpsert, *, has_series: bool = False) -> int:
        """Écrit l'enregistrement source et ses identifiants, et renvoie son id. La revue se rattache dans la phase `publishing`.

        Args:
            has_series: l'enregistrement source décrit une série ; avec sa monographie, cela décide de son éditeur (`source_record_has_publisher`).
        """
        params: dict[str, object] = {name: getattr(row, name) for name in _ROW_FIELDS}
        params["title"] = clean_publication_title(row.title)
        params["title_normalized"] = normalized_title(row.title)
        params["doc_type"] = _doc_type(row)
        if not source_record_has_publisher(
            params["doc_type"],
            row.source,
            has_container=has_series or row.monograph_id is not None,
        ):
            params["publisher_id"] = None
        if row.container_title and names_ebook_platform(row.container_title):
            params["container_title"] = None
        params["abstract"] = stored_abstract(row.abstract)
        params["language"] = language_code(row.raw_language, self._forms())
        params |= date_columns(row.publication_date)
        identifiers = normalized_identifiers(row)
        source_record_id = scalar_int(self._conn.execute(_UPSERT_SQL, params))
        replace_identifiers(self._conn, {source_record_id: identifiers})
        return source_record_id

    def _forms(self) -> dict[str, str]:
        if self._language_forms is None:
            self._language_forms = fetch_language_forms(self._conn)
        return self._language_forms


def _doc_type(row: SourceRecordUpsert) -> str | None:
    """Renvoie le type du référentiel correspondant au type de la source (`map_doc_type`). Un type absent de la table de sa source donne `other` et est journalisé."""
    if row.raw_doc_type is None:
        return None
    doc_type = map_doc_type(row.raw_doc_type, row.source)
    if doc_type is None:
        logger.warning(
            "Type de document inconnu (%s %s) : %r",
            row.source,
            row.source_id,
            row.raw_doc_type,
            extra={"detail": True},
        )
        return "other"
    return doc_type


def fetch_language_forms(conn: Connection) -> dict[str, str]:
    """Renvoie les formes de `language_forms`, chacune associée au code de sa langue."""
    rows = conn.execute(text("SELECT form_normalized, language_code FROM language_forms"))
    return {r.form_normalized: r.language_code for r in rows}


def normalized_identifiers(row: SourceRecordUpsert) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants normalisés de la ligne (`normalize_identifiers`). Chaque identifiant écarté est journalisé."""
    identifiers, rejected = normalize_identifiers(row.identifiers)
    for identifier in rejected:
        # Lignes de détail : le terminal les masque, le journal les garde.
        logger.warning(
            "Identifiant écarté (%s %s) : %s = %r",
            row.source,
            row.source_id,
            identifier.id_type,
            identifier.value,
            extra={"detail": True},
        )
    return identifiers


def _delete_source_records(conn: Connection, staging_filter: str, params: dict[str, object]) -> int:
    """Supprime les enregistrements sources à ligne de `staging` (alias `s`) conforme au filtre, et renvoie leur nombre.

    Les autres enregistrements sources de leur publication sont d'abord marqués pour la réconciliation : la phase `publications` recalcule la publication sans les enregistrements sources supprimés. La publication est marquée pour le groupement des auteurs. Une publication vidée de tous ses enregistrements sources est supprimée en fin de phase `publications`. Les contributions sources suivent par cascade.
    """
    enqueue(
        conn,
        Queue.PUBLICATION_CONTRIBUTIONS,
        f"""
            SELECT sr.publication_id
            FROM source_records sr
            JOIN staging s ON s.id = sr.staging_id
            WHERE {staging_filter} AND sr.publication_id IS NOT NULL
        """,  # noqa: S608
        params,
    )
    # noqa S608 : `staging_filter` est une constante de ce module, jamais une entrée.
    enqueue(
        conn,
        Queue.SOURCE_RECORD_KEYS,
        f"""
            SELECT soeur.id
            FROM source_records soeur
            JOIN source_records sr ON sr.publication_id = soeur.publication_id
            JOIN staging s ON s.id = sr.staging_id
            WHERE {staging_filter} AND soeur.id <> sr.id
        """,  # noqa: S608
        params,
    )
    return conn.execute(
        text(f"""
            DELETE FROM source_records sr
            USING staging s
            WHERE sr.staging_id = s.id AND {staging_filter}
        """),  # noqa: S608
        params,
    ).rowcount


def delete_source_record_of_staging(conn: Connection, staging_id: int) -> None:
    """Supprime l'enregistrement source d'une ligne de `staging` (`_delete_source_records`)."""
    _delete_source_records(conn, "s.id = :staging_id", {"staging_id": staging_id})


def delete_disappeared_source_records(conn: Connection) -> int:
    """Supprime les enregistrements sources des documents disparus de leur source (`_delete_source_records`). La ligne de `staging` reste, marquée disparue."""
    return _delete_source_records(conn, "s.disappeared_at IS NOT NULL", {})


def delete_source_records_before(conn: Connection, start_year: int) -> tuple[int, int]:
    """Supprime les enregistrements sources parus avant `start_year` (`_delete_source_records`), puis leur ligne de `staging`. Une thèse en cours reste : elle est sans année de soutenance.

    Renvoie le nombre d'enregistrements sources et de lignes de `staging` supprimés.
    """
    staging_ids = list(
        conn.execute(
            text("""
                SELECT sr.staging_id FROM source_records sr
                WHERE sr.publication_year < :start_year AND sr.staging_id IS NOT NULL
                  AND sr.doc_type IS DISTINCT FROM CAST(:ongoing AS doc_type)
            """),
            {"start_year": start_year, "ongoing": DocType.ONGOING_THESIS},
        ).scalars()
    )
    if not staging_ids:
        return 0, 0
    deleted = _delete_source_records(conn, "s.id = ANY(:ids)", {"ids": staging_ids})
    staged = conn.execute(
        text("DELETE FROM staging WHERE id = ANY(:ids)"), {"ids": staging_ids}
    ).rowcount
    return deleted, staged
