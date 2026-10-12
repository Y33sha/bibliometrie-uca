"""Table `doi_prefixes` : agence d'enregistrement (Registration Agency) et éditeur de chaque préfixe DOI.

Peuplée en deux temps : la phase `resolve_ra` insère `(prefix, ra)` ; le volet publisher de la phase `publishers_journals` interroge les API `/prefixes` pour les préfixes non encore vérifiés (`publisher_checked_at IS NULL`), renseigne les métadonnées et attache l'éditeur. Pour un préfixe DataCite, le nom et le symbole du client DataCite (repository) occupent des colonnes dédiées (`client_name_*`, `datacite_client_symbol`) ; le provider DataCite occupe les colonnes `publisher_*`, comme l'éditeur Crossref.

Sert la phase `resolve_ra` (lecture des préfixes à résoudre, insertion de leur Registration Agency) et le volet publisher de `publishers_journals` (attache de l'éditeur Crossref / repository DataCite).
"""

from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.source_publications.external_ids import ExternalIdType


class PendingPublisherPrefix(NamedTuple):
    """Row `doi_prefixes` dont le publisher reste à déterminer : `publisher_id IS NULL` et `publisher_checked_at IS NULL` (`/prefixes` jamais tenté). `publisher_name_*` sont en général NULL (créées par `resolve_ra` avec la RA seule) mais peuvent être renseignés pour des rows héritées — le volet attache alors directement sans re-fetch."""

    prefix: str
    ra: str
    publisher_name_raw: str | None
    publisher_name_normalized: str | None
    sample_doi: str | None = None
    """DOI du préfixe porté par un enregistrement, lu juste avant d'interroger Crossref."""


# Tous les DOI connus : DOI des notices, DOI liés, cibles des relations, DOI DataCite déduits des identifiants arXiv. Le nombre de préfixes reste petit : aucun filtre de périmètre.
_KNOWN_DOIS = f"""
    SELECT doi FROM source_publications WHERE doi IS NOT NULL
    UNION
    SELECT d.value FROM source_publications sp
    CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> '{ExternalIdType.RELATED_DOIS}') d(value)
    WHERE jsonb_typeof(sp.external_ids -> '{ExternalIdType.RELATED_DOIS}') = 'array'
    UNION
    SELECT target_doi FROM publication_relations WHERE target_doi IS NOT NULL
    UNION
    SELECT '10.48550/arxiv.' || lower(external_ids ->> 'arxiv_id') FROM source_publications
    WHERE external_ids ->> 'arxiv_id' IS NOT NULL
"""


class DoiPrefixesQueries:
    """Requêtes sur `doi_prefixes`, sur une connexion."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_prefixes_to_resolve(self) -> list[str]:
        """Préfixes de tous les DOI connus (`_KNOWN_DOIS`), qui couvrent les DOI que cherche la phase `fetch_missing`."""
        result = self._conn.execute(
            text(
                f"""
                SELECT DISTINCT split_part(c.doi, '/', 1) AS prefix
                FROM ({_KNOWN_DOIS}) c(doi)
                LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)
                WHERE c.doi <> '' AND dp.prefix IS NULL
                ORDER BY prefix
                """
            )
        )
        return [row.prefix for row in result]

    def insert_ra(self, *, prefix: str, ra: str) -> bool:
        """Insère un préfixe avec sa RA seule (`publisher_*` NULL, `publisher_checked_at` NULL). `ra='unknown'` si doi.org ne connaît pas le préfixe. Retourne True si inséré, False si déjà présent (`ON CONFLICT (prefix) DO NOTHING`)."""
        result = self._conn.execute(
            text(
                "INSERT INTO doi_prefixes (prefix, ra) VALUES (:prefix, :ra) "
                "ON CONFLICT (prefix) DO NOTHING"
            ),
            {"prefix": prefix, "ra": ra},
        )
        return result.rowcount > 0

    def breakdown_by_registration_agency(self) -> list[tuple[str, int, int]]:
        """Pour chaque Registration Agency présente parmi tous les DOI connus (`Crossref` / `DataCite` / `unknown`), le couple `(ra, nombre de DOI distincts, nombre de préfixes distincts)`, trié par nombre de DOI décroissant. Un DOI (ou préfixe) non encore résolu compte comme `unknown`. Sert l'observabilité de la phase `resolve_ra`."""
        result = self._conn.execute(
            text(
                f"""
                SELECT COALESCE(dp.ra, 'unknown') AS ra,
                       count(DISTINCT c.doi) AS dois,
                       count(DISTINCT split_part(c.doi, '/', 1)) AS prefixes
                FROM ({_KNOWN_DOIS}) c(doi)
                LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)
                WHERE c.doi <> ''
                GROUP BY COALESCE(dp.ra, 'unknown')
                ORDER BY count(DISTINCT c.doi) DESC
                """
            )
        )
        return [(row.ra, int(row.dois), int(row.prefixes)) for row in result]

    def get_prefixes_pending_publisher(self) -> list[PendingPublisherPrefix]:
        """Rows à traiter par le volet publisher : `publisher_id IS NULL`, `publisher_checked_at IS NULL`, et `ra` gérée (`Crossref`/`DataCite`/`unknown` — les autres RAs n'ont pas d'endpoint `/prefixes` exploitable). Ordre par `prefix` ASC pour des logs reproductibles."""
        result = self._conn.execute(
            text(
                """
                SELECT prefix, ra, publisher_name_raw, publisher_name_normalized
                FROM doi_prefixes
                WHERE publisher_id IS NULL
                  AND publisher_checked_at IS NULL
                  AND ra IN ('Crossref', 'DataCite', 'unknown')
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
        """Renseigne les métadonnées publisher d'une row après fetch `/prefixes` (et corrige `ra` si elle était `unknown`). N'attache pas le `publisher_id` (cf. `update_publisher_id`) ni ne marque la row vérifiée (cf. `mark_publisher_checked`)."""
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
        """Un DOI de ce préfixe porté par un enregistrement, qui sert à retrouver le membre Crossref déposant."""
        return self._conn.execute(
            text("SELECT doi FROM source_publications WHERE doi LIKE :motif LIMIT 1"),
            {"motif": f"{prefix}/%"},
        ).scalar()

    def update_publisher_id(self, prefix: str, publisher_id: int) -> None:
        """Attache un publisher à un préfixe."""
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_id = :pid WHERE prefix = :prefix"),
            {"pid": publisher_id, "prefix": prefix},
        )

    def mark_publisher_checked(self, prefix: str) -> None:
        """Pose `publisher_checked_at = now()` : `/prefixes` a répondu, préfixe trouvé ou absent → la row ne sera plus reprise par le volet."""
        self._conn.execute(
            text("UPDATE doi_prefixes SET publisher_checked_at = now() WHERE prefix = :prefix"),
            {"prefix": prefix},
        )
