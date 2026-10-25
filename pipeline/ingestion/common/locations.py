"""Localisations d'un enregistrement source et plateformes qui les hébergent. L'écriture est commune aux normaliseurs.

Les localisations d'un enregistrement source se réécrivent à chaque normalisation, comme l'enregistrement lui-même : le dernier import fait autorité. Un identifiant arXiv ou PMCID de l'enregistrement donne aussi une localisation, quelle que soit la source. Une plateforme se reconnaît par son identifiant OpenAlex. Une plateforme de la liste des plateformes connues (`domain.platforms.registry`) en prend le nom et le type ; une autre prend le nom que lui donne OpenAlex.
"""

import json
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.platforms.platform import PlatformType
from domain.platforms.registry import IDENTIFIER_COPIES, KnownPlatform
from domain.publications.licenses import License
from domain.source_records.external_ids import normalize_external_ids
from domain.types import JsonValue
from infrastructure.db.scalars import scalar_int


class PlatformFacts(NamedTuple):
    """Plateforme d'une localisation, telle que la source la décrit."""

    openalex_id: str
    name: str
    platform_type: PlatformType


class LocationFacts(NamedTuple):
    """Localisation d'un document, telle que la source la décrit."""

    url: str
    pdf_url: str | None = None
    oai_id: str | None = None
    version: str | None = None
    license: License | None = None
    is_oa: bool | None = None
    platform: PlatformFacts | None = None


def known_platform_facts(known: KnownPlatform) -> PlatformFacts:
    """Plateforme d'une localisation sur une plateforme connue, reconnue par sa source OpenAlex principale."""
    return PlatformFacts(known.openalex_ids[0], known.name, known.platform_type)


def identifier_locations(external_ids: JsonValue) -> list[LocationFacts]:
    """Copies ouvertes que désignent l'identifiant arXiv et le PMCID d'un enregistrement source, sans version connue."""
    if not isinstance(external_ids, Mapping):
        return []
    ids, _ = normalize_external_ids(external_ids)
    return [
        LocationFacts(url=url.format(value), is_oa=True, platform=known_platform_facts(known))
        for id_type, url, known in IDENTIFIER_COPIES
        if isinstance(value := ids.get(id_type), str)
    ]


# Le nom et le type suivent la source à chaque écriture.
_UPSERT_PLATFORM = text("""
    INSERT INTO platforms (name, name_normalized, platform_type, openalex_id)
    VALUES (:name, :name_normalized, CAST(:platform_type AS platform_type), :openalex_id)
    ON CONFLICT (openalex_id) DO UPDATE SET
        name = EXCLUDED.name, name_normalized = EXCLUDED.name_normalized,
        platform_type = EXCLUDED.platform_type
    RETURNING id
""")

_DELETE_LOCATIONS = text("DELETE FROM source_record_locations WHERE source_record_id = :id")

_INSERT_LOCATIONS = text("""
    INSERT INTO source_record_locations
        (source_record_id, url, pdf_url, oai_id, version, license, is_oa, platform_id)
    SELECT :id, l.url, l.pdf_url, l.oai_id, l.version, CAST(l.license AS license_type), l.is_oa,
           l.platform_id
    FROM jsonb_to_recordset(CAST(:locations AS jsonb)) AS l(
        url text, pdf_url text, oai_id text, version text, license text, is_oa boolean,
        platform_id integer
    )
""")


class LocationStore:
    """Écriture des localisations et des plateformes, sur la connexion `conn`. Les plateformes déjà vues se gardent en mémoire."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._platforms: dict[str, int] = {}

    def platform_id(self, platform: PlatformFacts) -> int:
        """Identifiant de la plateforme, trouvée ou créée par son identifiant OpenAlex."""
        if platform.openalex_id not in self._platforms:
            self._platforms[platform.openalex_id] = scalar_int(
                self._conn.execute(
                    _UPSERT_PLATFORM,
                    {
                        "name": platform.name,
                        "name_normalized": normalize_text(platform.name),
                        "platform_type": platform.platform_type.value,
                        "openalex_id": platform.openalex_id,
                    },
                )
            )
        return self._platforms[platform.openalex_id]

    def replace_locations(self, source_record_id: int, locations: Sequence[LocationFacts]) -> None:
        """Remplace les localisations de l'enregistrement source par `locations`, une par URL."""
        self._conn.execute(_DELETE_LOCATIONS, {"id": source_record_id})
        # Parcours à rebours : une URL en double garde sa première localisation.
        rows = {
            loc.url: {
                "url": loc.url,
                "pdf_url": loc.pdf_url,
                "oai_id": loc.oai_id,
                "version": loc.version,
                "license": loc.license.value if loc.license else None,
                "is_oa": loc.is_oa,
                "platform_id": self.platform_id(loc.platform) if loc.platform else None,
            }
            for loc in reversed(locations)
        }
        if rows:
            self._conn.execute(
                _INSERT_LOCATIONS,
                {"id": source_record_id, "locations": json.dumps(list(rows.values()))},
            )
