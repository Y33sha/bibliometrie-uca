"""Localisations d'un enregistrement source et plateformes d'hébergement. L'écriture est commune aux normaliseurs.

Les localisations d'un enregistrement source se réécrivent à chaque normalisation, comme l'enregistrement source lui-même : le dernier import fait autorité. Un identifiant arXiv ou un PMCID de l'enregistrement source donne aussi une localisation, quelle que soit la source. La plateforme d'une localisation est celle nommée par OpenAlex, reconnue par son identifiant OpenAlex. La lecture des copies rattache en plus chaque localisation à une plateforme de la liste des plateformes connues, d'après son URL (`domain.platforms.registry`).
"""

import json
from collections.abc import Iterable, Sequence
from datetime import date
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.platforms.platform import PlatformType, is_descriptive_page
from domain.platforms.registry import IDENTIFIER_COPIES
from domain.publications.licenses import License
from domain.source_records.identifiers import SourceIdentifier, normalize_identifiers
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
    """Copie ouverte, à la fin de son embargo s'il y en a un."""
    platform: PlatformFacts | None = None
    embargo_until: date | None = None


def identifier_locations(identifiers: Iterable[SourceIdentifier]) -> list[LocationFacts]:
    """Renvoie les copies ouvertes désignées par les identifiants arXiv et les PMCID d'un enregistrement source, sans version connue."""
    identifiers, _ = normalize_identifiers(identifiers)
    return [
        LocationFacts(url=IDENTIFIER_COPIES[i.id_type].format(i.value), is_oa=True)
        for i in identifiers
        if i.id_type in IDENTIFIER_COPIES
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
        (source_record_id, url, pdf_url, oai_id, version, license, is_oa, platform_id,
         embargo_until)
    SELECT :id, l.url, l.pdf_url, l.oai_id, l.version, CAST(l.license AS license_type), l.is_oa,
           l.platform_id, l.embargo_until
    FROM jsonb_to_recordset(CAST(:locations AS jsonb)) AS l(
        url text, pdf_url text, oai_id text, version text, license text, is_oa boolean,
        platform_id integer, embargo_until date
    )
""")


class LocationStore:
    """Écriture des localisations et des plateformes, sur la connexion `conn`. Les plateformes déjà vues se gardent en mémoire."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._platforms: dict[str, int] = {}

    def platform_id(self, platform: PlatformFacts) -> int:
        """Renvoie l'identifiant de la plateforme, trouvée ou créée par son identifiant OpenAlex."""
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
        """Réécrit les localisations de l'enregistrement source avec `locations`, une par URL, hors pages descriptives."""
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
                "embargo_until": loc.embargo_until.isoformat() if loc.embargo_until else None,
            }
            for loc in reversed(locations)
            if not is_descriptive_page(loc.url)
        }
        if rows:
            self._conn.execute(
                _INSERT_LOCATIONS,
                {"id": source_record_id, "locations": json.dumps(list(rows.values()))},
            )
