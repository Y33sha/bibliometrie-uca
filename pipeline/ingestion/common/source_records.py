"""Écriture et suppression des `source_records`. L'écriture est commune aux normaliseurs de toutes les sources.

Un enregistrement source est la vue normalisée d'un import : le dernier import fait autorité. L'UPSERT réécrit donc toutes les colonnes de l'enregistrement depuis la ligne fournie, sans conserver de valeur antérieure. Seule la clé `(source, source_id)` traverse les imports, ce qui maintient l'`id` de la ligne stable pour les tables qui la référencent — d'où l'UPSERT plutôt qu'un DELETE suivi d'un INSERT.

L'écriture ne porte que sur les colonnes de la ligne : celles qu'aucun import ne renseigne traversent l'UPSERT intactes. C'est le cas de `publication_id`, que la phase `publications` pose et recalcule pour les lignes marquées `keys_dirty` — ce que chaque écriture fait ici. C'est aussi le cas du cache `countries`, alimenté par la phase du même nom, et de `created_at`.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date

from sqlalchemy import Connection, bindparam, text

from domain.publications.licenses import License
from domain.publications.metadata import normalized_title
from domain.source_records.doc_types import map_doc_type
from domain.source_records.external_ids import normalize_external_ids
from domain.source_records.languages import language_code
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.queues import Queue, enqueue
from infrastructure.db.scalars import scalar_int

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRecordUpsert:
    """Un enregistrement `source_records` tel qu'une source le fournit, prêt à être écrit.

    Le jeu de colonnes est commun à toutes les sources ; celles qu'une source ne renseigne pas restent à `None`. Cette absence reflète ce que la source expose : theses.fr ne fournit pas de résumé, HAL et theses.fr pas d'indicateur de citation, `hal_collections` et `embargo_until` n'existent que pour HAL, `is_retracted` que pour OpenAlex.

    Quatre colonnes de `source_records` n'y figurent pas. `title_normalized` se dérive de `title` au moment de l'écriture, `doc_type` de `raw_doc_type` (`map_doc_type`) et `language` de `raw_language` (`language_code`). `publication_id` est le rattachement à la publication, que la phase `publications` pose et que l'import ne connaît pas.
    """

    # Clé de l'enregistrement source
    source: str
    source_id: str
    """Identifiant natif de la source : hal-id, id OpenAlex, UT WoS, id ScanR, id theses.fr ou NNT, DOI pour crossref et datacite."""
    staging_id: int

    # Rattachement
    doi: str | None = None
    external_ids: JsonValue = None

    # Métadonnées bibliographiques
    title: str
    publication_year: int | None = None
    raw_doc_type: str | None = None
    """Type de document dans le vocabulaire de la source."""
    journal_id: int | None = None
    monograph_id: int | None = None
    container_title: str | None = None
    raw_language: str | None = None
    """Langue dans le vocabulaire de la source."""
    biblio: JsonValue = None

    # Contenu
    abstract: str | None = None
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


_FIELDS = fields(SourceRecordUpsert)

# Les colonnes écrites se dérivent des champs de la ligne, plus les colonnes
# calculées à l'écriture : un champ ajouté à `SourceRecordUpsert` est inséré et
# réécrit sans autre geste, en phase avec le contrat.
_ROW_FIELDS = tuple(f.name for f in _FIELDS)
_COLUMNS = (*_ROW_FIELDS, "title_normalized", "doc_type", "language")

# Tout est réécrit sauf la clé de conflit, qui est justement ce qui identifie la ligne. `corrections` se vide : les
# valeurs d'origine qu'il garde viennent de l'import précédent, et la phase `metadata_correction` refait ses
# corrections sur les valeurs fraîches.
_UPDATED_COLUMNS = tuple(c for c in _COLUMNS if c not in ("source", "source_id"))

# Colonnes JSONB : les champs annotés `JsonValue` (les `list[str]` sont des `text[]`,
# hors JSONB). Un champ JSONB ajouté au contrat est typé sans autre geste.
_JSONB_COLUMNS = tuple(f.name for f in _FIELDS if f.type is JsonValue)

# Colonnes à type énuméré PostgreSQL : le paramètre est converti vers ce type.
_ENUM_CASTS = {"doc_type": "doc_type", "license": "license_type"}


def _value(column: str) -> str:
    cast = _ENUM_CASTS.get(column)
    return f"CAST(:{column} AS {cast})" if cast else f":{column}"


_UPSERT_SQL = text(
    f"""
    INSERT INTO source_records ({", ".join(_COLUMNS)})
    VALUES ({", ".join(_value(c) for c in _COLUMNS)})
    ON CONFLICT (source, source_id) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATED_COLUMNS)},
        corrections = '{{}}'::jsonb,
        keys_dirty = true,
        updated_at = clock_timestamp()
    RETURNING id
    """  # noqa: S608 — listes de colonnes construites depuis le contrat, sans entrée externe
).bindparams(*(bindparam(c, type_=Jsonb) for c in _JSONB_COLUMNS))


class SourceRecordStore:
    """Écriture des `source_records`. Les formes de `language_forms` se chargent à la première écriture."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._language_forms: dict[str, str] | None = None

    def upsert_source_record(self, row: SourceRecordUpsert) -> int:
        params: dict[str, object] = {name: getattr(row, name) for name in _ROW_FIELDS}
        params["title_normalized"] = normalized_title(row.title)
        params["doc_type"] = _doc_type(row)
        params["language"] = language_code(row.raw_language, self._forms())
        params["external_ids"] = _external_ids(row)
        return scalar_int(self._conn.execute(_UPSERT_SQL, params))

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


def _external_ids(row: SourceRecordUpsert) -> dict[str, JsonValue]:
    """`external_ids` normalisé, objet JSON vide à défaut : la colonne est `NOT NULL` et contrainte à un objet. Chaque entrée écartée est journalisée."""
    if row.external_ids is None:
        return {}
    if not isinstance(row.external_ids, Mapping):
        # Lignes de détail : le terminal les masque, le journal les garde.
        logger.warning(
            "external_ids écarté (%s %s) : objet attendu, reçu %r",
            row.source,
            row.source_id,
            row.external_ids,
            extra={"detail": True},
        )
        return {}
    clean, rejected = normalize_external_ids(row.external_ids)
    for entry in rejected:
        logger.warning(
            "external_ids écarté (%s %s) : %s = %r",
            row.source,
            row.source_id,
            entry.key,
            entry.value,
            extra={"detail": True},
        )
    return clean


def _delete_source_records(conn: Connection, staging_filter: str, params: dict[str, object]) -> int:
    """Supprime les `source_records` dont la ligne de `staging` (alias `s`) satisfait `staging_filter`.

    Les `source_records` rattachées à la même publication sont d'abord marquées `keys_dirty` : la phase `publications` réconcilie alors la publication et recalcule ses métadonnées sans la source retirée. La publication est marquée pour le groupement des auteurs. Une publication vidée de toutes ses sources est supprimée en fin de phase `publications`. Les `source_contributions` suivent par cascade. Rend le nombre de `source_records` supprimées.
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
    conn.execute(
        text(f"""
            UPDATE source_records soeur
            SET keys_dirty = true
            FROM source_records sr
            JOIN staging s ON s.id = sr.staging_id
            WHERE {staging_filter}
              AND soeur.publication_id = sr.publication_id
              AND soeur.id <> sr.id
              AND NOT soeur.keys_dirty
        """),  # noqa: S608
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


def delete_source_records_before(
    conn: Connection, start_year: int, *, exempt_sources: tuple[str, ...]
) -> tuple[int, int]:
    """Supprime les enregistrements sources parus avant `start_year` (cf. `_delete_source_records`), puis leur ligne de `staging`. Les enregistrements sources des sources `exempt_sources` restent.

    Rend le nombre de `source_records` et de lignes de `staging` supprimées.
    """
    staging_ids = list(
        conn.execute(
            text("""
                SELECT sr.staging_id FROM source_records sr
                WHERE sr.publication_year < :start_year AND sr.staging_id IS NOT NULL
                  AND sr.source::text <> ALL(:exempt)
            """),
            {"start_year": start_year, "exempt": list(exempt_sources)},
        ).scalars()
    )
    if not staging_ids:
        return 0, 0
    deleted = _delete_source_records(conn, "s.id = ANY(:ids)", {"ids": staging_ids})
    staged = conn.execute(
        text("DELETE FROM staging WHERE id = ANY(:ids)"), {"ids": staging_ids}
    ).rowcount
    return deleted, staged
