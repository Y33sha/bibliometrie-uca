"""Pays candidats des adresses (`address_country_candidates`) et marqueur des adresses à traiter (`addresses.candidates_dirty`).

Chaque moyen de détection ajoute ses candidats et marque les adresses qui en reçoivent un. La résolution (`resolution.py`) compose ensuite `addresses.countries`.
"""

import json

from sqlalchemy import Connection, text

from domain.country_detection import CountryDetectionMethod

# Fin partagée des insertions de candidats : attend une CTE `added(address_id)` des candidats ajoutés, marque leurs adresses à traiter et compte ces adresses.
_MARK_DIRTY = """,
    marked AS (
        UPDATE addresses SET candidates_dirty = true
        WHERE id IN (SELECT address_id FROM added) AND NOT candidates_dirty
    )
    SELECT count(DISTINCT address_id) FROM added
"""


class CountryCandidatesStore:
    """Pays candidats des adresses, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def dirty_addresses(self) -> list[tuple[int, str]]:
        """`(id, normalized_text)` des adresses à traiter (`candidates_dirty`), pour la détection par le texte."""
        rows = self._conn.execute(
            text("SELECT id, normalized_text FROM addresses WHERE candidates_dirty")
        ).all()
        return [(r.id, r.normalized_text) for r in rows]

    def add(self, method: CountryDetectionMethod, rows: list[tuple[int, list[str]]]) -> int:
        """Ajoute les candidats `(adresse, pays)` de `rows` pour le moyen `method`, et marque `candidates_dirty` les adresses qui en reçoivent un. Un candidat déjà présent, ou un code absent du référentiel des pays, est ignoré. Retourne le nombre d'adresses qui reçoivent un candidat."""
        if not rows:
            return 0
        payload = json.dumps([{"id": addr_id, "c": codes} for addr_id, codes in rows])
        marked = self._conn.execute(
            text(
                """
                WITH proposed AS (
                    SELECT DISTINCT (e->>'id')::int AS address_id, code.value AS country_code
                    FROM jsonb_array_elements(CAST(:payload AS jsonb)) e
                    CROSS JOIN LATERAL jsonb_array_elements_text(e->'c') code
                    JOIN countries c ON c.code = code.value
                ), added AS (
                    INSERT INTO address_country_candidates (address_id, country_code, method)
                    SELECT address_id, country_code, CAST(:method AS country_detection_method)
                    FROM proposed
                    ON CONFLICT DO NOTHING
                    RETURNING address_id
                )"""
                + _MARK_DIRTY
            ),
            {"payload": payload, "method": method.value},
        ).scalar_one()
        return int(marked)

    def replace_for_dirty_addresses(
        self, method: CountryDetectionMethod, rows: list[tuple[int, list[str]]]
    ) -> int:
        """Efface les candidats du moyen `method` des adresses `candidates_dirty`, puis écrit ceux de `rows`, qui concernent ces seules adresses. Retourne le nombre d'adresses qui reçoivent un candidat."""
        self._conn.execute(
            text("""
                DELETE FROM address_country_candidates
                WHERE method = CAST(:method AS country_detection_method)
                  AND address_id IN (SELECT id FROM addresses WHERE candidates_dirty)
            """),
            {"method": method.value},
        )
        return self.add(method, rows)

    def add_ror(self) -> int:
        """Ajoute le pays de chaque organisation ROR rattachée à l'affiliation d'une adresse (candidat `ror`), et marque `candidates_dirty` les adresses qui en reçoivent un. Retourne le nombre d'adresses qui reçoivent un candidat."""
        marked = self._conn.execute(
            text(
                """
                WITH added AS (
                    INSERT INTO address_country_candidates (address_id, country_code, method)
                    SELECT DISTINCT scr.address_id, ro.country_code, 'ror'::country_detection_method
                    FROM source_contribution_rors scr
                    JOIN ror_organizations ro ON ro.ror_id = scr.ror_id
                    JOIN countries c ON c.code = ro.country_code
                    WHERE scr.address_id IS NOT NULL
                    ON CONFLICT DO NOTHING
                    RETURNING address_id
                )"""
                + _MARK_DIRTY
            )
        ).scalar_one()
        return int(marked)

    def mark_all_for_detection(self) -> int:
        """Marque `candidates_dirty` toutes les adresses : le run suivant refait la détection par le texte et la résolution sur tout le stock. Retourne le nombre d'adresses marquées."""
        return self._conn.execute(
            text("UPDATE addresses SET candidates_dirty = true WHERE NOT candidates_dirty")
        ).rowcount
