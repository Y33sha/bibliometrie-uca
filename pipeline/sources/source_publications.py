"""Écriture des `source_publications`, commune aux normaliseurs de toutes les sources.

Une `source_publication` est la vue normalisée d'un import : le dernier import fait autorité. L'UPSERT réécrit donc toutes les colonnes de l'enregistrement depuis la ligne fournie, sans conserver de valeur antérieure. Seule l'identité `(source, source_id)` traverse les imports, ce qui maintient l'`id` de la ligne stable pour les tables qui la référencent — d'où l'UPSERT plutôt qu'un DELETE suivi d'un INSERT.

L'écriture ne porte que sur les colonnes de la ligne : celles qu'aucun import ne renseigne traversent l'UPSERT intactes. C'est le cas de `publication_id`, que la phase `publications` pose et recalcule pour les lignes marquées `keys_dirty` — ce que chaque écriture fait ici. C'est aussi le cas du cache `countries`, alimenté par la phase du même nom, et de `created_at`.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date

from sqlalchemy import Connection, bindparam, text

from domain.publications.metadata import normalized_title
from domain.source_publications.external_ids import normalize_external_ids
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.scalars import scalar_int

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourcePublicationUpsert:
    """Un enregistrement `source_publications` tel qu'une source le fournit, prêt à être écrit.

    Le jeu de colonnes est commun à toutes les sources ; celles qu'une source ne renseigne pas restent à `None`. Cette absence reflète ce que la source expose : theses.fr ne fournit pas de résumé, HAL et theses.fr pas d'indicateur de citation, `hal_collections` et `embargo_until` n'existent que pour HAL, `is_retracted` que pour OpenAlex.

    Deux colonnes de `source_publications` n'y figurent pas. `title_normalized` se dérive de `title` au moment de l'écriture. `publication_id` est le rattachement à la publication canonique, que la phase `publications` pose et que l'import ne connaît pas.
    """

    # Identité de l'enregistrement source
    source: str
    source_id: str
    """Identifiant natif de la source : hal-id, id OpenAlex, UT WoS, id ScanR, id theses.fr ou NNT, DOI pour crossref et datacite."""
    staging_id: int

    # Rattachement
    doi: str | None = None
    external_ids: JsonValue = None

    # Métadonnées bibliographiques
    title: str
    pub_year: int | None = None
    doc_type: str | None = None
    journal_id: int | None = None
    monograph_id: int | None = None
    container_title: str | None = None
    language: str | None = None
    biblio: JsonValue = None

    # Contenu
    abstract: str | None = None
    keywords: list[str] | None = None
    topics: JsonValue = None

    # Accès ouvert
    oa_status: str | None = None
    urls: list[str] | None = None
    embargo_until: date | None = None

    # Citations et drapeaux
    impact: JsonValue = None
    """Indicateurs de citation, construits par `domain.source_publications.impact.Impact.to_json`."""
    is_retracted: bool | None = None

    # Collections HAL
    hal_collections: list[str] | None = None

    # Charge utile propre à la source
    meta: JsonValue = None


_FIELDS = fields(SourcePublicationUpsert)

# Les colonnes écrites se dérivent des champs de la ligne, plus `title_normalized`
# calculé à l'écriture : un champ ajouté à `SourcePublicationUpsert` est inséré et
# réécrit sans autre geste, en phase avec le contrat.
_ROW_FIELDS = tuple(f.name for f in _FIELDS)
_COLUMNS = (*_ROW_FIELDS, "title_normalized")

# Tout est réécrit sauf la clé de conflit, qui est justement ce qui identifie la ligne. `raw_metadata` se vide : les
# valeurs d'origine qu'il garde viennent de l'import précédent, et la phase `metadata_correction` refait ses
# corrections sur les valeurs fraîches.
_UPDATED_COLUMNS = tuple(c for c in _COLUMNS if c not in ("source", "source_id"))

# Colonnes JSONB : les champs annotés `JsonValue` (les `list[str]` sont des `text[]`,
# hors JSONB). Un champ JSONB ajouté au contrat est typé sans autre geste.
_JSONB_COLUMNS = tuple(f.name for f in _FIELDS if f.type is JsonValue)

_UPSERT_SQL = text(
    f"""
    INSERT INTO source_publications ({", ".join(_COLUMNS)})
    VALUES ({", ".join(f":{c}" for c in _COLUMNS)})
    ON CONFLICT (source, source_id) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATED_COLUMNS)},
        raw_metadata = '{{}}'::jsonb,
        keys_dirty = true,
        updated_at = clock_timestamp()
    RETURNING id
    """  # noqa: S608 — listes de colonnes construites depuis le contrat, sans entrée externe
).bindparams(*(bindparam(c, type_=Jsonb) for c in _JSONB_COLUMNS))


class SourcePublicationQueries:
    """Écriture des `source_publications`."""

    def upsert_source_publication(self, conn: Connection, row: SourcePublicationUpsert) -> int:
        params: dict[str, object] = {name: getattr(row, name) for name in _ROW_FIELDS}
        params["title_normalized"] = normalized_title(row.title)
        params["external_ids"] = _external_ids(row)
        return scalar_int(conn.execute(_UPSERT_SQL, params))


def _external_ids(row: SourcePublicationUpsert) -> dict[str, JsonValue]:
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
