"""Projection SQL des candidats du canal identifiant (record linkage).

Fournit à `domain.persons.identifier_graph.cluster_by_identifier` les identités porteuses
d'un identifiant fort nu, avec le détenteur éventuel de chaque valeur (personne existante)
et le verdict de corroboration forme de l'identité ↔ détenteur.
"""

from sqlalchemy import Connection, text

from domain.persons.identifier_graph import IdentifierCandidate

# Une ligne par (identité, type d'identifiant fort nu). Le détenteur de la valeur (au plus
# un, contrainte UNIQUE sur person_identifiers) et le verdict de corroboration sont joints
# quand ils existent. Le verdict combine statut admin et appartenance au nom canonique :
# un rejet l'emporte, sinon une confirmation admin ou une forme dérivée du nom canonique
# corrobore (cf. `fetch_name_form_status_map`).
_CANDIDATES_SQL = text("""
    WITH strong_ids AS (
        SELECT aik.id AS identity_id,
               aik.author_name_normalized AS identity_name,
               k.k AS id_type,
               (aik.person_identifiers ->> k.k) AS id_value
        FROM author_identifying_keys aik
        CROSS JOIN unnest(ARRAY['orcid', 'idref', 'hal_person_id', 'idhal']) k(k)
        WHERE aik.person_identifiers ? k.k
          AND (aik.person_identifiers ->> k.k) NOT LIKE '%_dubious'
    )
    SELECT s.identity_id, s.identity_name, s.id_type, s.id_value,
           pi.person_id AS anchor_person_id,
           p.last_name_normalized AS anchor_last_norm,
           p.first_name_normalized AS anchor_first_norm,
           v.verdict
    FROM strong_ids s
    LEFT JOIN person_identifiers pi
           ON pi.id_type = s.id_type AND pi.id_value = s.id_value AND pi.status <> 'rejected'
    LEFT JOIN persons p ON p.id = pi.person_id
    LEFT JOIN LATERAL (
        SELECT CASE WHEN status = 'rejected' THEN 'rejected' ELSE 'confirmed' END AS verdict
        FROM person_name_forms pnf
        WHERE pnf.person_id = pi.person_id AND pnf.name_form = s.identity_name
          AND (pnf.status IN ('rejected', 'confirmed') OR 'persons' = ANY(pnf.sources))
        LIMIT 1
    ) v ON true
""")


def fetch_identifier_candidates(conn: Connection) -> list[IdentifierCandidate]:
    """Charge les candidats du canal identifiant (une ligne par identité × identifiant)."""
    return [
        IdentifierCandidate(
            identity_id=r.identity_id,
            identity_name=r.identity_name,
            id_type=r.id_type,
            id_value=r.id_value,
            anchor_person_id=r.anchor_person_id,
            anchor_last_norm=r.anchor_last_norm or "",
            anchor_first_norm=r.anchor_first_norm or "",
            verdict=r.verdict,
        )
        for r in conn.execute(_CANDIDATES_SQL)
    ]
