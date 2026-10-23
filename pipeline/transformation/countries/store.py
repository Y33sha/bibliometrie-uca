"""Pays candidats des adresses (`address_country_candidates`) et file des adresses à traiter (`address_candidates_queue`).

Un candidat ajouté hors de la détection par le texte marque son adresse. La détection par le texte traite les adresses en file. La résolution (`resolution.py`) compose ensuite `addresses.countries`.
"""

import json

from sqlalchemy import Connection, text

from domain.country_detection import CountryDetectionMethod
from infrastructure.db.queues import Queue, enqueue, enqueue_sql

# Insertion des candidats `(adresse, pays)` d'un moyen, depuis un payload JSON ; ouvre la CTE `added(address_id)` des candidats ajoutés.
_INSERT_PROPOSED = """
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

# Fin des insertions de candidats : compte les adresses de la CTE `added`.
_COUNT_ADDED = """
    SELECT count(DISTINCT address_id) FROM added
"""

# Fin des insertions de candidats : marque les adresses de la CTE `added`, puis les compte.
_MARK_AND_COUNT_ADDED = (
    f""",
    marked AS ({enqueue_sql(Queue.ADDRESS_CANDIDATES, "SELECT address_id FROM added")})"""
    + _COUNT_ADDED
)


def _payload(rows: list[tuple[int, list[str]]]) -> str:
    return json.dumps([{"id": addr_id, "c": codes} for addr_id, codes in rows])


class CountryCandidatesStore:
    """Pays candidats des adresses, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def queued_addresses(self) -> list[tuple[int, str]]:
        """`(id, normalized_text)` des adresses en file, pour la détection par le texte."""
        rows = self._conn.execute(
            text(
                f"SELECT a.id, a.normalized_text FROM addresses a JOIN {Queue.ADDRESS_CANDIDATES} q ON q.id = a.id"  # noqa: S608
            )
        ).all()
        return [(r.id, r.normalized_text) for r in rows]

    def add(self, method: CountryDetectionMethod, rows: list[tuple[int, list[str]]]) -> int:
        """Ajoute les candidats `(adresse, pays)` de `rows` pour le moyen `method`, et marque les adresses qui en reçoivent un. Un candidat déjà présent, ou un code absent du référentiel des pays, est ignoré. Retourne le nombre d'adresses qui reçoivent un candidat."""
        if not rows:
            return 0
        return int(
            self._conn.execute(
                text(_INSERT_PROPOSED + _MARK_AND_COUNT_ADDED),
                {"payload": _payload(rows), "method": method.value},
            ).scalar_one()
        )

    def replace_for_queued_addresses(
        self, method: CountryDetectionMethod, rows: list[tuple[int, list[str]]]
    ) -> int:
        """Efface les candidats du moyen `method` des adresses en file, puis écrit ceux de `rows`, qui concernent ces seules adresses. Retourne le nombre d'adresses qui reçoivent un candidat."""
        self._conn.execute(
            text(f"""
                DELETE FROM address_country_candidates
                WHERE method = CAST(:method AS country_detection_method)
                  AND address_id IN (SELECT id FROM {Queue.ADDRESS_CANDIDATES})
            """),  # noqa: S608
            {"method": method.value},
        )
        if not rows:
            return 0
        return int(
            self._conn.execute(
                text(_INSERT_PROPOSED + _COUNT_ADDED),
                {"payload": _payload(rows), "method": method.value},
            ).scalar_one()
        )

    def add_ror(self) -> int:
        """Ajoute le pays de chaque organisation ROR rattachée à l'affiliation d'une adresse (candidat `ror`), et marque les adresses qui en reçoivent un. Retourne le nombre d'adresses qui reçoivent un candidat."""
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
                + _MARK_AND_COUNT_ADDED
            )
        ).scalar_one()
        return int(marked)

    def mark_all_for_detection(self) -> int:
        """Marque toutes les adresses : le run suivant refait la détection par le texte et la résolution sur tout le stock. Retourne le nombre d'adresses marquées."""
        return enqueue(self._conn, Queue.ADDRESS_CANDIDATES, "SELECT id FROM addresses", {})
