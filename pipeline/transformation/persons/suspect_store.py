"""Accès SQL de la phase `suspect_attributions` : indices des publications des personnes à fiche RH, fréquence des indices, profils des publications rejetées, écriture de `suspect_contributions`."""

from collections import defaultdict
from collections.abc import Collection, Sequence

from sqlalchemy import Connection, text

from domain.contributions.contribution_roles import THESIS_JURY_ROLES
from domain.persons.contribution_matching import ContributionMatchReason
from domain.persons.name_matching import names_compatible
from domain.persons.suspect_attributions import (
    CLUE_HAL_STRUCTURE_TYPES,
    ClueFamily,
    ClueFrequencies,
    PublicationClues,
    SuspectReason,
)
from domain.persons.tie_break import ContributionContext
from domain.structures.structure import StructureType
from domain.subjects.subject import SubjectVocabulary
from infrastructure.sql_fragments import REJECTED_PAIRS, in_clause
from pipeline.transformation.persons.store import fetch_contribution_contexts

_TOPIC = (SubjectVocabulary.OPENALEX, 4)
_HAL_DOMAIN = (SubjectVocabulary.HAL_DOMAIN, 2)

_OUTSIDE_THESIS_JURY = f"""
    NOT (g.roles IS NOT NULL AND cardinality(g.roles) > 0
         AND g.roles <@ ARRAY[{", ".join(f"'{r}'" for r in sorted(THESIS_JURY_ROLES))}]::text[])
"""
"""Contribution hors des seuls rôles de jury de thèse."""

_RETAINED_PERSONS = "SELECT id FROM persons WHERE exclusion IS NULL"
"""Personnes examinées : une personne exclue (fausse entité, hors périmètre) est écartée de la détection."""


def _subjects(vocabulary: str, level: int) -> str:
    return f"""
        ARRAY(SELECT ps.subject_id FROM publication_subjects ps JOIN subjects s ON s.id = ps.subject_id
              WHERE ps.publication_id = g.publication_id AND NOT ps.rejected
                AND s.vocabulary::text = '{vocabulary}' AND s.level = {level})
    """


_CLUES_SQL = f"""
    SELECT g.id, g.person_id, g.resolution_mode::text AS mode,
           (SELECT count(*) FROM contributions o WHERE o.publication_id = g.publication_id) AS contribution_count,
           EXISTS (SELECT 1 FROM aligned_source_contributions gm
                   JOIN source_contribution_addresses sca ON sca.source_contribution_id = gm.source_contribution_id
                   JOIN address_structures ast ON ast.address_id = sca.address_id
                   JOIN hr_periods hp ON hp.structure_id = ast.structure_id AND hp.person_id = g.person_id
                   WHERE gm.contribution_id = g.id) AS confirmed,
           p.serial_id,
           ARRAY(SELECT o.person_id FROM contributions o
                 WHERE o.publication_id = g.publication_id AND o.id <> g.id
                   AND o.person_id IS NOT NULL AND o.person_id <> g.person_id) AS coauthors,
           ARRAY(SELECT DISTINCT scs.structure_id FROM aligned_source_contributions gm
                 JOIN source_contribution_structures scs ON scs.source_contribution_id = gm.source_contribution_id
                 JOIN structures s ON s.id = scs.structure_id
                 WHERE gm.contribution_id = g.id AND s.structure_type::text = '{StructureType.LABO}') AS laboratories,
           ARRAY(SELECT DISTINCT sch.hal_structure_id FROM aligned_source_contributions gm
                 JOIN source_contribution_hal_structures sch ON sch.source_contribution_id = gm.source_contribution_id
                 JOIN hal_structures h ON h.hal_structure_id = sch.hal_structure_id
                 WHERE gm.contribution_id = g.id
                   AND h.structure_type IN {in_clause(CLUE_HAL_STRUCTURE_TYPES)}) AS hal_structures,
           {_subjects(*_TOPIC)} AS topics,
           {_subjects(*_HAL_DOMAIN)} AS hal_domains
    FROM contributions g
    JOIN publications p ON p.id = g.publication_id
    WHERE g.person_id IN (SELECT person_id FROM hr_records)
      AND g.person_id IN ({_RETAINED_PERSONS})
      AND {_OUTSIDE_THESIS_JURY}
"""


def fetch_publication_clues(conn: Connection) -> dict[int, list[PublicationClues]]:
    """Renvoie les indices des publications de chaque personne à fiche RH retenue, hors contributions des seuls rôles de jury de thèse. Une contribution est confirmée quand une de ses adresses est rattachée à une structure de la fiche RH de la personne."""
    by_person: dict[int, list[PublicationClues]] = defaultdict(list)
    for r in conn.execute(text(_CLUES_SQL)):
        clues = {(ClueFamily.COAUTHOR, p) for p in r.coauthors}
        clues |= {(ClueFamily.LABORATORY, s) for s in r.laboratories}
        clues |= {(ClueFamily.HAL_STRUCTURE, h) for h in r.hal_structures}
        clues |= {(ClueFamily.TOPIC, s) for s in r.topics}
        clues |= {(ClueFamily.HAL_DOMAIN, s) for s in r.hal_domains}
        if r.serial_id is not None:
            clues.add((ClueFamily.SERIAL, r.serial_id))
        by_person[r.person_id].append(
            PublicationClues(
                r.id,
                ContributionMatchReason(r.mode),
                frozenset(clues),
                contribution_count=r.contribution_count,
                confirmed=r.confirmed,
            )
        )
    return by_person


_STRUCTURE_FREQUENCIES_SQL = """
    SELECT link.{column}, count(DISTINCT sr.publication_id)
    FROM {table} link
    JOIN source_contributions sc ON sc.id = link.source_contribution_id
    JOIN source_records sr ON sr.id = sc.source_record_id
    WHERE sr.publication_id IS NOT NULL
    GROUP BY 1
"""

_FREQUENCIES_SQL: dict[ClueFamily, str] = {
    ClueFamily.SERIAL: "SELECT serial_id, count(*) FROM publications WHERE serial_id IS NOT NULL GROUP BY 1",
    ClueFamily.COAUTHOR: "SELECT person_id, count(*) FROM contributions WHERE person_id IS NOT NULL GROUP BY 1",
    ClueFamily.LABORATORY: _STRUCTURE_FREQUENCIES_SQL.format(
        column="structure_id", table="source_contribution_structures"
    ),
    ClueFamily.HAL_STRUCTURE: _STRUCTURE_FREQUENCIES_SQL.format(
        column="hal_structure_id", table="source_contribution_hal_structures"
    ),
}

_SUBJECT_FREQUENCIES_SQL = """
    SELECT subject_id, count(DISTINCT publication_id) FROM publication_subjects
    WHERE NOT rejected GROUP BY 1
"""


def fetch_clue_frequencies(conn: Connection) -> ClueFrequencies:
    """Renvoie le nombre de publications de la base et la fréquence de chaque indice."""
    counts = {
        family: {r[0]: r[1] for r in conn.execute(text(sql))}
        for family, sql in _FREQUENCIES_SQL.items()
    }
    subjects = {r[0]: r[1] for r in conn.execute(text(_SUBJECT_FREQUENCIES_SQL))}
    counts[ClueFamily.TOPIC] = subjects
    counts[ClueFamily.HAL_DOMAIN] = subjects
    publication_count = conn.execute(text("SELECT count(*) FROM publications")).scalar_one()
    return ClueFrequencies(max(publication_count, 2), counts)


_REJECTED_NAMED_SQL = f"""
    WITH rejected AS MATERIALIZED (
        SELECT DISTINCT publication_id, person_id FROM ({REJECTED_PAIRS}) rp
        WHERE publication_id IS NOT NULL AND person_id IN ({_RETAINED_PERSONS})
    )
    SELECT r.publication_id, r.person_id, g.id AS contribution_id,
           p.last_name_normalized AS person_last, p.first_name_normalized AS person_first,
           ci.last_name_normalized AS last, coalesce(ci.first_name_normalized, '') AS first
    FROM rejected r
    JOIN persons p ON p.id = r.person_id
    JOIN source_records sr ON sr.publication_id = r.publication_id
    JOIN source_contributions sc ON sc.source_record_id = sr.id
    JOIN contributor_information ci
      ON ci.id = sc.contributor_information_id AND ci.last_name_normalized = p.last_name_normalized
    JOIN aligned_source_contributions gm ON gm.source_contribution_id = sc.id
    JOIN contributions g ON g.id = gm.contribution_id
    WHERE g.person_id IS DISTINCT FROM r.person_id
"""


def fetch_rejected_profiles(conn: Connection) -> dict[int, list[ContributionContext]]:
    """Renvoie le profil des publications rejetées pour chaque personne retenue : dans chaque publication rejetée, la seule contribution au nom de la personne, quelle que soit sa personne."""
    named: dict[tuple[int, int], set[int]] = defaultdict(set)
    for r in conn.execute(text(_REJECTED_NAMED_SQL)):
        if names_compatible(r.last, r.first, r.person_last, r.person_first):
            named[(r.publication_id, r.person_id)].add(r.contribution_id)
    unique = {next(iter(ids)): person for (_, person), ids in named.items() if len(ids) == 1}
    contexts = fetch_contribution_contexts(conn, sorted(unique))
    profiles: dict[int, list[ContributionContext]] = defaultdict(list)
    for contribution_id, person_id in unique.items():
        if contribution_id in contexts:
            profiles[person_id].append(contexts[contribution_id])
    return profiles


def fetch_candidate_contributions(
    conn: Connection, person_ids: Collection[int]
) -> list[tuple[int, int]]:
    """Renvoie les contributions `(contribution, personne)` des personnes, hors épinglage et hors contributions des seuls rôles de jury de thèse."""
    rows = conn.execute(
        text(f"""
            SELECT g.id, g.person_id FROM contributions g
            WHERE g.person_id = ANY(:persons) AND g.resolution_mode::text <> 'manual'
              AND {_OUTSIDE_THESIS_JURY}
        """),
        {"persons": list(person_ids)},
    )
    return [(r.id, r.person_id) for r in rows]


def write_suspect_contributions(
    conn: Connection, rows: Sequence[tuple[int, int, SuspectReason, int | None]]
) -> None:
    """Écrit le contenu de `suspect_contributions` : les lignes `(contribution, personne, motif, cluster)`, seules dans la table."""
    conn.execute(text("DELETE FROM suspect_contributions"))
    if rows:
        conn.execute(
            text("""
                INSERT INTO suspect_contributions (contribution_id, person_id, reason, cluster)
                VALUES (:contribution, :person, CAST(:reason AS suspect_reason), :cluster)
            """),
            [
                {"contribution": c, "person": p, "reason": reason.value, "cluster": cluster}
                for c, p, reason, cluster in rows
            ],
        )
