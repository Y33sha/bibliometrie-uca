"""Store de la table `doi_prefixes` : agence d'enregistrement (Registration Agency) et éditeur de chaque préfixe DOI.

La phase `resolve_ra` insère chaque préfixe avec son agence. La phase `publishing` interroge ensuite l'API `/prefixes` de Crossref, puis celle de DataCite, et attache l'éditeur. Pour un préfixe DataCite, l'éditeur est le provider DataCite ; le client DataCite (repository) a ses propres colonnes.
"""

from typing import Literal, NamedTuple

from sqlalchemy import Connection, text

from domain.source_records.identifiers import SourceIdentifierType

type Agency = Literal["Crossref", "DataCite"]
"""Agence dont l'API `/prefixes` donne l'éditeur d'un préfixe."""

# Préfixes encore jamais vus par l'agence. Un préfixe d'agence inconnue passe chez DataCite après sa vérification par Crossref.
_PENDING: dict[Agency, str] = {
    "Crossref": "crossref_checked_at IS NULL AND ra IN ('Crossref', 'unknown')",
    "DataCite": (
        "datacite_checked_at IS NULL"
        " AND (ra = 'DataCite' OR (ra = 'unknown' AND crossref_checked_at IS NOT NULL))"
    ),
}

_CHECKED_COLUMN: dict[Agency, str] = {
    "Crossref": "crossref_checked_at",
    "DataCite": "datacite_checked_at",
}


class PendingPublisherPrefix(NamedTuple):
    """Préfixe en attente de son éditeur."""

    prefix: str
    ra: str
    publisher_name_raw: str | None
    """En général vide : `resolve_ra` crée la ligne avec l'agence seule. Un nom présent dispense de la requête à l'agence."""
    publisher_name_normalized: str | None
    sample_doi: str | None = None
    """DOI d'un enregistrement source de ce préfixe, lu juste avant d'interroger Crossref."""


class DoiPrefixStore:
    """Requêtes sur `doi_prefixes`, sur une connexion."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_prefixes_to_resolve(self) -> list[str]:
        """Renvoie les préfixes absents de la table parmi les DOI connus (vue `known_dois`), tous périmètres confondus. Ils couvrent les DOI cherchés par la phase `fetch_missing`."""
        result = self._conn.execute(
            text(
                """
                SELECT DISTINCT split_part(c.doi, '/', 1) AS prefix
                FROM known_dois c
                LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)
                WHERE c.doi <> '' AND dp.prefix IS NULL
                ORDER BY prefix
                """
            )
        )
        return [row.prefix for row in result]

    def insert_ra(self, *, prefix: str, ra: str) -> bool:
        """Insère un préfixe avec sa seule agence, `unknown` pour un préfixe inconnu de doi.org. Renvoie vrai si le préfixe est absent de la table."""
        result = self._conn.execute(
            text(
                "INSERT INTO doi_prefixes (prefix, ra) VALUES (:prefix, :ra) "
                "ON CONFLICT (prefix) DO NOTHING"
            ),
            {"prefix": prefix, "ra": ra},
        )
        return result.rowcount > 0

    def breakdown_by_registration_agency(self) -> list[tuple[str, int, int]]:
        """Renvoie le nombre de DOI et de préfixes de chaque agence parmi les DOI connus, par nombre de DOI décroissant. Un préfixe absent de la table compte comme `unknown`. Sert au journal de la phase `resolve_ra`."""
        result = self._conn.execute(
            text(
                """
                SELECT COALESCE(dp.ra, 'unknown') AS ra,
                       count(DISTINCT c.doi) AS dois,
                       count(DISTINCT split_part(c.doi, '/', 1)) AS prefixes
                FROM known_dois c
                LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)
                WHERE c.doi <> ''
                GROUP BY COALESCE(dp.ra, 'unknown')
                ORDER BY count(DISTINCT c.doi) DESC
                """
            )
        )
        return [(row.ra, int(row.dois), int(row.prefixes)) for row in result]

    def get_prefixes_pending_publisher(self, agency: Agency) -> list[PendingPublisherPrefix]:
        """Renvoie les préfixes sans éditeur encore jamais vus par l'agence, par ordre de préfixe."""
        result = self._conn.execute(
            text(
                f"""
                SELECT prefix, ra, publisher_name_raw, publisher_name_normalized
                FROM doi_prefixes
                WHERE publisher_id IS NULL AND {_PENDING[agency]}
                ORDER BY prefix
                """
            )
        )
        return [
            PendingPublisherPrefix(
                prefix=r.prefix,
                ra=r.ra,
                publisher_name_raw=r.publisher_name_raw,
                publisher_name_normalized=r.publisher_name_normalized,
            )
            for r in result
        ]

    def set_prefix_publisher_metadata(
        self,
        *,
        prefix: str,
        ra: str,
        publisher_name_raw: str | None,
        publisher_name_normalized: str | None,
        crossref_member_id: int | None,
        client_name_raw: str | None,
        client_name_normalized: str | None,
        datacite_client_symbol: str | None,
    ) -> None:
        """Pose l'agence et les métadonnées d'éditeur données par l'API `/prefixes`. `update_publisher_id` attache l'éditeur, `mark_checked` retient la réponse de l'agence."""
        self._conn.execute(
            text(
                """
                UPDATE doi_prefixes SET
                    ra = :ra,
                    publisher_name_raw = :publisher_name_raw,
                    publisher_name_normalized = :publisher_name_normalized,
                    crossref_member_id = :crossref_member_id,
                    client_name_raw = :client_name_raw,
                    client_name_normalized = :client_name_normalized,
                    datacite_client_symbol = :datacite_client_symbol
                WHERE prefix = :prefix
                """
            ),
            {
                "prefix": prefix,
                "ra": ra,
                "publisher_name_raw": publisher_name_raw,
                "publisher_name_normalized": publisher_name_normalized,
                "crossref_member_id": crossref_member_id,
                "client_name_raw": client_name_raw,
                "client_name_normalized": client_name_normalized,
                "datacite_client_symbol": datacite_client_symbol,
            },
        )

    def find_doi_with_prefix(self, prefix: str) -> str | None:
        """Renvoie un DOI actif d'enregistrement source de ce préfixe. Il sert à retrouver le membre Crossref déposant."""
        return self._conn.execute(
            text(f"""
                SELECT id_value FROM source_record_identifiers
                WHERE id_type = '{SourceIdentifierType.DOI.value}' AND removed_by IS NULL
                  AND id_value LIKE :motif
                LIMIT 1
            """),
            {"motif": f"{prefix}/%"},
        ).scalar()

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        """Attache un éditeur à un préfixe."""
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_id = :pid WHERE prefix = :prefix"),
            {"pid": publisher_id, "prefix": prefix},
        )

    def mark_checked(self, prefix: str, agency: Agency) -> None:
        """Retient que l'agence a répondu pour ce préfixe, connu d'elle ou non."""
        self._conn.execute(
            text(
                f"UPDATE doi_prefixes SET {_CHECKED_COLUMN[agency]} = now() WHERE prefix = :prefix"
            ),
            {"prefix": prefix},
        )
