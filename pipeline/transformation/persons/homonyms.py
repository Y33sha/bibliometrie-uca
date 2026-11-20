"""Tâche `persons.attach_homonyms` : contributions des publications rejetées pour une personne, rattachées à l'homonyme de la personne (`domain.persons.homonyms`).

Dans une publication rejetée pour une personne, la seule contribution sans personne au nom de la personne (`homonym_contribution`) rejoint l'homonyme de la personne, sous le mode `homonym`. L'homonyme est créé au besoin : fiche au nom de la personne, exclue hors périmètre, reliée à la personne par `persons.homonym_of`. Une contribution rattachée à l'homonyme sans rejet qui la désigne perd sa personne. Un homonyme sans contribution est supprimé.
"""

from collections import defaultdict

from sqlalchemy import Connection, text

from domain.persons.contribution_matching import ContributionMatchReason
from domain.persons.homonyms import Name, homonym_contribution
from domain.persons.person import PersonExclusion
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import DETACHED_CONTRIBUTION, REJECTED_PAIRS

_HOMONYM = ContributionMatchReason.HOMONYM

_CANDIDATES_SQL = text(f"""
    WITH rejected AS (
        SELECT DISTINCT publication_id, person_id FROM ({REJECTED_PAIRS}) rp
        WHERE publication_id IS NOT NULL
    )
    SELECT r.publication_id, r.person_id, p.last_name_normalized AS person_last,
           p.first_name_normalized AS person_first, g.id AS contribution_id,
           ci.last_name_normalized AS last, coalesce(ci.first_name_normalized, '') AS first
    FROM rejected r
    JOIN persons p ON p.id = r.person_id AND p.homonym_of IS NULL
    JOIN contributions g ON g.publication_id = r.publication_id
         AND (g.person_id IS NULL OR g.resolution_mode = '{_HOMONYM}')
    JOIN aligned_source_contributions gm ON gm.contribution_id = g.id
    JOIN source_contributions sc ON sc.id = gm.source_contribution_id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE ci.last_name_normalized <> ''
      AND (strpos(ci.last_name_normalized, p.last_name_normalized) > 0
           OR strpos(p.last_name_normalized, ci.last_name_normalized) > 0
           OR strpos(coalesce(ci.first_name_normalized, ''), p.last_name_normalized) > 0)
""")
"""Contributions sans personne ou rattachées à un homonyme des publications rejetées pour une personne, avec les noms de leurs contributions sources. Un nom de famille contenu dans celui de la personne, ou le contenant, filtre les contributions sources."""

_HOMONYMS_SQL = text("""
    SELECT homonym_of, min(id) AS id FROM persons
    WHERE homonym_of = ANY(:persons) GROUP BY homonym_of
""")

_PERSONS_SQL = text("SELECT id, last_name, first_name FROM persons WHERE id = ANY(:ids)")

_LINK_SQL = text("UPDATE persons SET homonym_of = :person WHERE id = :homonym")

_CURRENT_SQL = text(f"SELECT id, person_id FROM contributions WHERE resolution_mode = '{_HOMONYM}'")

_RELEASE_SQL = text(f"UPDATE contributions SET {DETACHED_CONTRIBUTION} WHERE id = ANY(:ids)")

_ATTACH_SQL = text(f"""
    UPDATE contributions g SET person_id = u.person_id, resolution_mode = '{_HOMONYM}'
    FROM unnest(CAST(:ids AS integer[]), CAST(:persons AS integer[])) AS u(id, person_id)
    WHERE g.id = u.id AND (g.person_id IS NULL OR g.resolution_mode = '{_HOMONYM}')
      AND g.person_id IS DISTINCT FROM u.person_id
""")

_DELETE_EMPTY_SQL = text("""
    DELETE FROM persons p
    WHERE p.homonym_of IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM contributions g WHERE g.person_id = p.id)
""")


def homonym_targets(conn: Connection) -> dict[int, int]:
    """Renvoie la personne rejetée de chaque contribution qui rejoint son homonyme (`homonym_contribution`). Une contribution désignée pour deux personnes est écartée."""
    names: dict[tuple[int, int], dict[int, list[Name]]] = defaultdict(lambda: defaultdict(list))
    person_names: dict[int, Name] = {}
    for r in conn.execute(_CANDIDATES_SQL):
        person_names[r.person_id] = (r.person_last, r.person_first)
        names[(r.publication_id, r.person_id)][r.contribution_id].append((r.last, r.first))
    targets: dict[int, int] = {}
    ambiguous: set[int] = set()
    for (_, person_id), contributions in names.items():
        contribution_id = homonym_contribution(person_names[person_id], contributions)
        if contribution_id is None:
            continue
        if contribution_id in targets and targets[contribution_id] != person_id:
            ambiguous.add(contribution_id)
        targets[contribution_id] = person_id
    return {c: p for c, p in targets.items() if c not in ambiguous}


def ensure_homonyms(conn: Connection, person_ids: set[int]) -> tuple[dict[int, int], int]:
    """Renvoie l'homonyme de chaque personne, créé s'il manque, et le nombre d'homonymes créés. Une personne à plusieurs homonymes, réunis par une fusion, garde le premier."""
    homonyms = {
        r.homonym_of: r.id for r in conn.execute(_HOMONYMS_SQL, {"persons": list(person_ids)})
    }
    missing = sorted(person_ids - homonyms.keys())
    repo = PgPersonRepository(conn)
    for r in conn.execute(_PERSONS_SQL, {"ids": missing}):
        homonym_id = repo.create(r.last_name, r.first_name)
        repo.set_exclusion(homonym_id, PersonExclusion.OUT_OF_PERIMETER)
        conn.execute(_LINK_SQL, {"person": r.id, "homonym": homonym_id})
        homonyms[r.id] = homonym_id
    return homonyms, len(missing)


def attach_homonyms(conn: Connection) -> dict[str, int]:
    """Rattache aux homonymes les contributions des publications rejetées, détache celles sans rejet, supprime les homonymes sans contribution. Renvoie les compteurs."""
    targets = homonym_targets(conn)
    homonyms, created = ensure_homonyms(conn, set(targets.values()))
    planned = {c: homonyms[p] for c, p in targets.items()}
    released = [r.id for r in conn.execute(_CURRENT_SQL) if planned.get(r.id) != r.person_id]
    if released:
        conn.execute(_RELEASE_SQL, {"ids": released})
    attached = 0
    if planned:
        attached = conn.execute(
            _ATTACH_SQL, {"ids": list(planned), "persons": list(planned.values())}
        ).rowcount
    deleted = conn.execute(_DELETE_EMPTY_SQL).rowcount
    return {
        "homonyms_created": created,
        "homonyms_deleted": deleted,
        "homonym_contributions_attached": attached,
        "homonym_contributions_released": len(released),
    }
