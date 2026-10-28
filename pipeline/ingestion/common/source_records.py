"""Écriture et suppression des `source_records`. L'écriture est commune aux normaliseurs de toutes les sources.

Un enregistrement source est la vue normalisée d'un import : le dernier import fait autorité. L'UPSERT réécrit donc toutes les colonnes de l'enregistrement depuis la ligne fournie, sans conserver de valeur antérieure. Seule la clé `(source, source_id)` traverse les imports, ce qui maintient l'`id` de la ligne stable pour les tables qui la référencent — d'où l'UPSERT plutôt qu'un DELETE suivi d'un INSERT.

L'écriture concerne seulement les colonnes de la ligne : celles qu'aucun import ne renseigne traversent l'UPSERT intactes. C'est le cas de `publication_id`, que la phase `publications` pose et recalcule pour les lignes de la file `source_record_keys_queue`, où chaque écriture met la ligne. C'est aussi le cas du cache `countries`, alimenté par la phase du même nom, et de `created_at`.
"""

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import date

from sqlalchemy import Connection, bindparam, text

from domain.normalize import drop_duplicate_mathml, strip_abstract_label
from domain.publications.doc_types import DocType
from domain.publications.licenses import License
from domain.publications.metadata import normalized_title
from domain.publishers.attribution import source_record_has_publisher
from domain.serials.titles import names_ebook_platform
from domain.source_records.doc_types import map_doc_type
from domain.source_records.external_ids import external_ids_from_identifiers
from domain.source_records.identifiers import SourceIdentifier, normalize_identifiers
from domain.source_records.languages import language_code
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue, enqueue_sql
from infrastructure.db.scalars import scalar_int

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRecordUpsert:
    """Un enregistrement `source_records` tel qu'une source le fournit, prêt à être écrit.

    Le jeu de colonnes est commun à toutes les sources ; celles qu'une source ne renseigne pas restent à `None`. Cette absence reflète ce que la source expose : theses.fr ne fournit pas de résumé, HAL et theses.fr pas d'indicateur de citation, `hal_collections` et `embargo_until` n'existent que pour HAL, `is_retracted` que pour OpenAlex.

    Cinq colonnes de `source_records` n'y figurent pas. `title_normalized` se dérive de `title` au moment de l'écriture, `doc_type` de `raw_doc_type` (`map_doc_type`), `language` de `raw_language` (`language_code`) et `external_ids` de `identifiers`. `publication_id` est le rattachement à la publication, que la phase `publications` pose et que l'import ne connaît pas.
    """

    # Clé de l'enregistrement source
    source: str
    source_id: str
    """Identifiant natif de la source : hal-id, id OpenAlex, UT WoS, id ScanR, id theses.fr ou NNT, DOI pour crossref et datacite."""
    staging_id: int

    # Rattachement
    doi: str | None = None
    identifiers: tuple[SourceIdentifier, ...] = ()
    """Identifiants de l'enregistrement source, avec leur rôle, écrits dans `source_record_identifiers`. L'écriture les normalise et en déduit `external_ids`."""

    # Métadonnées bibliographiques
    title: str
    publication_year: int | None = None
    raw_doc_type: str | None = None
    """Type de document dans le vocabulaire de la source."""
    serial_id: int | None = None
    monograph_id: int | None = None
    publisher_id: int | None = None
    """Éditeur que nomme la source. L'écriture le retire d'une production hébergée sans être publiée (`source_record_has_publisher`)."""
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

    # Accès ouvert
    oa_status: str | None = None
    license: License | None = None
    urls: list[str] | None = None
    embargo_until: date | None = None

    # Citations et drapeaux
    impact: JsonValue = None
    """Indicateurs de citation, construits par `domain.source_records.impact.Impact.to_json`."""
    is_retracted: bool | None = None

    # Collections HAL
    hal_collections: list[str] | None = None

    # Charge utile propre à la source
    source_extras: JsonValue = None


_FIELDS = tuple(f for f in fields(SourceRecordUpsert) if f.name != "identifiers")

# Les colonnes écrites se dérivent des champs de la ligne, plus les colonnes
# calculées à l'écriture : un champ ajouté à `SourceRecordUpsert` est inséré et
# réécrit sans autre geste, en phase avec le contrat.
_ROW_FIELDS = tuple(f.name for f in _FIELDS)
_COLUMNS = (*_ROW_FIELDS, "title_normalized", "doc_type", "language", "external_ids")

# Tout est réécrit sauf la clé de conflit, qui est justement ce qui identifie la ligne. `corrections` se vide : les
# valeurs d'origine qu'il garde viennent de l'import précédent, et la phase `metadata_correction` refait ses
# corrections sur les valeurs fraîches.
_UPDATED_COLUMNS = tuple(c for c in _COLUMNS if c not in ("source", "source_id"))

# Colonnes JSONB : les champs annotés `JsonValue` (les `list[str]` sont des `text[]`,
# hors JSONB). Un champ JSONB ajouté au contrat est typé sans autre geste.
_JSONB_COLUMNS = (*(f.name for f in _FIELDS if f.type is JsonValue), "external_ids")

# Colonnes à type énuméré PostgreSQL : le paramètre est converti vers ce type.
_ENUM_CASTS = {"doc_type": "doc_type", "license": "license_type"}


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
    """Remplace les identifiants de chaque enregistrement source de `identifiers_by_source_record`, en une suppression et une insertion. Chaque identifiant écrit est actif."""
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


class SourceRecordStore:
    """Écriture des `source_records` et de leurs identifiants. Les formes de `language_forms` se chargent à la première écriture."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._language_forms: dict[str, str] | None = None

    def upsert_source_record(self, row: SourceRecordUpsert) -> int:
        params: dict[str, object] = {name: getattr(row, name) for name in _ROW_FIELDS}
        params["title_normalized"] = normalized_title(row.title)
        params["doc_type"] = _doc_type(row)
        if not source_record_has_publisher(
            params["doc_type"],
            row.source,
            has_container=row.serial_id is not None or row.monograph_id is not None,
        ):
            params["publisher_id"] = None
        if row.container_title and names_ebook_platform(row.container_title):
            params["container_title"] = None
        params["abstract"] = strip_abstract_label(drop_duplicate_mathml(row.abstract))
        params["language"] = language_code(row.raw_language, self._forms())
        identifiers = normalized_identifiers(row)
        params["external_ids"] = external_ids_from_identifiers(identifiers, row.doi)
        source_record_id = scalar_int(self._conn.execute(_UPSERT_SQL, params))
        replace_identifiers(self._conn, {source_record_id: identifiers})
        return source_record_id

    def _forms(self) -> dict[str, str]:
        if self._language_forms is None:
            self._language_forms = fetch_language_forms(self._conn)
        return self._language_forms


def _doc_type(row: SourceRecordUpsert) -> str | None:
    """Type du référentiel de `row.raw_doc_type` (`map_doc_type`). Un type inconnu de la table de sa source donne `other` et est journalisé."""
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
    """Formes de `language_forms`, chacune associée au code de sa langue."""
    rows = conn.execute(text("SELECT form_normalized, language_code FROM language_forms"))
    return {r.form_normalized: r.language_code for r in rows}


def normalized_identifiers(row: SourceRecordUpsert) -> tuple[SourceIdentifier, ...]:
    """Identifiants normalisés de la ligne (`normalize_identifiers`). Chaque identifiant écarté est journalisé."""
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
    """Supprime les `source_records` dont la ligne de `staging` (alias `s`) satisfait `staging_filter`.

    Les `source_records` rattachées à la même publication sont d'abord marquées pour la réconciliation : la phase `publications` réconcilie alors la publication et recalcule ses métadonnées sans la source retirée. La publication est marquée pour le groupement des auteurs. Une publication vidée de toutes ses sources est supprimée en fin de phase `publications`. Les `source_contributions` suivent par cascade. Rend le nombre de `source_records` supprimées.
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
    """Supprime la `source_record` de la ligne de `staging` `staging_id` (cf. `_delete_source_records`)."""
    _delete_source_records(conn, "s.id = :staging_id", {"staging_id": staging_id})


def delete_disappeared_source_records(conn: Connection) -> int:
    """Supprime les `source_records` dont le staging porte `disappeared_at` (cf. `_delete_source_records`). La ligne de `staging` reste, avec sa marque.

    Balayage ensembliste, idempotent.
    """
    return _delete_source_records(conn, "s.disappeared_at IS NOT NULL", {})


def delete_source_records_before(conn: Connection, start_year: int) -> tuple[int, int]:
    """Supprime les enregistrements sources parus avant `start_year` (cf. `_delete_source_records`), puis leur ligne de `staging`. Une thèse en cours reste : elle n'a pas d'année de soutenance.

    Rend le nombre de `source_records` et de lignes de `staging` supprimées.
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
