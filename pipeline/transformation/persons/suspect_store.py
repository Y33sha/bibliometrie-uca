"""Accès SQL de la phase `suspect_attributions` : indices des publications des personnes à fiche RH, fréquence des indices, profils de la ressemblance aux rejets, écriture de `suspect_contributions`."""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from sqlalchemy import Connection, Row, text

from domain.contributions.contribution_roles import THESIS_JURY_ROLES
from domain.persons.contribution_matching import TIE_BREAK_REASONS, ContributionMatchReason
from domain.persons.name_matching import names_compatible
from domain.persons.suspect_attributions import (
    CLUE_HAL_STRUCTURE_TYPES,
    LARGE_COLLABORATION,
    ClueFamily,
    ClueFrequencies,
    PublicationClues,
    SuspectReason,
    coauthor_key,
)
from domain.persons.tie_break import ContributionContext
from domain.structures.perimeter_evidence import PerimeterEvidence
from domain.structures.structure import StructureType
from domain.subjects.subject import SubjectVocabulary
from infrastructure.sql_fragments import in_clause

_TOPIC = (SubjectVocabulary.OPENALEX, 4)
_HAL_DOMAIN = (SubjectVocabulary.HAL_DOMAIN, 2)

_OUTSIDE_THESIS_JURY = f"""
    NOT (g.roles IS NOT NULL AND cardinality(g.roles) > 0
         AND g.roles <@ ARRAY[{", ".join(f"'{r}'" for r in sorted(THESIS_JURY_ROLES))}]::text[])
"""
"""Contribution hors des seuls rôles de jury de thèse."""

_RETAINED_PERSONS = "SELECT id FROM persons WHERE exclusion IS NULL"
"""Personnes examinées : une personne exclue (fausse entité, hors périmètre) est écartée de la détection."""


def _orcid_given_by(source_condition: str) -> str:
    """Renvoie la condition SQL : une contribution source de la contribution `g`, de source `source_condition`, comporte un ORCID non rejeté de la personne."""
    return f"""
        EXISTS (SELECT 1 FROM aligned_source_contributions gm
                JOIN source_contributions sc ON sc.id = gm.source_contribution_id
                JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                JOIN person_identifiers pi
                  ON pi.person_id = g.person_id AND pi.id_type = 'orcid' AND pi.status::text <> 'rejected'
                 AND ci.identifiers->>'orcid' = pi.id_value
                WHERE gm.contribution_id = g.id AND sc.source::text {source_condition})
    """


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
                   JOIN source_contributions sc ON sc.id = gm.source_contribution_id
                   WHERE gm.contribution_id = g.id
                     AND '{PerimeterEvidence.ADDRESS}' = ANY(sc.perimeter_evidence)) AS perimeter_address,
           {_orcid_given_by("= 'hal'")} AND NOT {_orcid_given_by("<> 'hal'")} AS orcid_from_hal_only,
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
    """Renvoie les indices des publications de chaque personne à fiche RH retenue, hors contributions des seuls rôles de jury de thèse."""
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
                perimeter_address=r.perimeter_address,
                orcid_from_hal_only=r.orcid_from_hal_only,
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


_REJECTED_RECORDS_SQL = f"""
    SELECT rc.person_id, sr.id AS record, sr.publication_id, sr.title_normalized,
           coalesce(sr.serial_id, p.serial_id) AS serial_id,
           coalesce(sr.publication_year, p.publication_year) AS year
    FROM rejected_contributions rc
    JOIN source_records sr ON sr.source = rc.source AND sr.source_id = rc.source_id
    LEFT JOIN publications p ON p.id = sr.publication_id
    WHERE rc.person_id IN ({_RETAINED_PERSONS})
"""
"""Enregistrements sources rejetés pour une personne retenue, avec ou sans publication."""

_OWN_CONTRIBUTIONS_SQL = f"""
    SELECT g.id, g.person_id, g.publication_id, p.serial_id, p.publication_year AS year,
           g.resolution_mode::text IN {in_clause(TIE_BREAK_REASONS)} AS tie_break,
           g.resolution_mode::text <> 'manual' AND {_OUTSIDE_THESIS_JURY} AS candidate,
           ARRAY(SELECT gm.source_contribution_id FROM aligned_source_contributions gm
                 WHERE gm.contribution_id = g.id) AS own_source_contributions
    FROM contributions g JOIN publications p ON p.id = g.publication_id
    WHERE g.person_id = ANY(:persons)
"""
"""Contributions des personnes à rejets : profil de la personne hors rattachement par départage, candidates hors épinglage et hors seuls rôles de jury de thèse."""

_SOURCE_CONTRIBUTIONS_SQL = """
    WITH records AS MATERIALIZED (
        SELECT id, publication_id FROM source_records
        WHERE id = ANY(:records) OR publication_id = ANY(:publications)
    ),
    large AS MATERIALIZED (
        SELECT sc.source_record_id FROM source_contributions sc
        JOIN records r ON r.id = sc.source_record_id
        GROUP BY 1 HAVING count(*) > :large
    )
    SELECT sc.id, sr.id AS record, sr.publication_id,
           ci.last_name_normalized AS last, coalesce(ci.first_name_normalized, '') AS first
    FROM records sr
    JOIN source_contributions sc ON sc.source_record_id = sr.id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    WHERE sr.id NOT IN (SELECT source_record_id FROM large)
       OR ci.last_name_normalized = ANY(:last_names)
"""
"""Noms des contributions sources des enregistrements rejetés et des publications : toutes pour un enregistrement d'au plus `LARGE_COLLABORATION` contributions sources, seulement celles au nom d'une personne examinée au-delà. Une grande collaboration n'apporte pas de coauteurs."""

_STRUCTURES_SQL = """
    SELECT scs.source_contribution_id, 'laboratory' AS kind, scs.structure_id AS structure
    FROM source_contribution_structures scs JOIN structures s ON s.id = scs.structure_id
    WHERE scs.source_contribution_id = ANY(:ids) AND s.structure_type::text = :labo
    UNION ALL
    SELECT sch.source_contribution_id, 'hal_structure', sch.hal_structure_id
    FROM source_contribution_hal_structures sch
    JOIN hal_structures h ON h.hal_structure_id = sch.hal_structure_id
    WHERE sch.source_contribution_id = ANY(:ids) AND h.structure_type = ANY(:hal_types)
"""
"""Laboratoires et structures HAL des contributions sources de la personne."""


@dataclass(frozen=True)
class NameProfiles:
    """Contextes de la ressemblance aux rejets, coauteurs décrits par leur clé de nom (`coauthor_key`)."""

    own: dict[int, list[ContributionContext]]
    """Profil de chaque personne : ses contributions, hors rattachement par départage."""
    rejected: dict[int, list[ContributionContext]]
    """Profil des publications rejetées pour chaque personne, publication purgée comprise."""
    candidates: list[tuple[int, int, ContributionContext]]
    """Contributions à juger : (contribution, personne, contexte)."""


@dataclass(frozen=True)
class _Document:
    """Document à mettre en contexte : publication, ou titre d'enregistrements sources sans publication."""

    document_id: int
    person_id: int
    source_contributions: list[Row[tuple[object, ...]]]
    own: frozenset[int]
    """Contributions sources de la personne."""
    serial_id: int | None
    year: int | None


def _context(
    document: _Document,
    person_key: tuple[str, str],
    structures: Mapping[int, list[tuple[str, int]]],
) -> ContributionContext:
    """Renvoie le contexte d'un document : coauteurs par clé de nom hors personne, laboratoires et structures HAL des contributions sources de la personne."""
    coauthors = {
        key
        for sc in document.source_contributions
        if sc.id not in document.own and (key := coauthor_key(sc.last, sc.first)) != person_key
    }
    owned = [s for sc_id in document.own for s in structures.get(sc_id, ())]
    return ContributionContext(
        document.document_id,
        frozenset(coauthors),
        frozenset(s for kind, s in owned if kind == "laboratory"),
        frozenset(s for kind, s in owned if kind == "hal_structure"),
        document.serial_id,
        document.year,
    )


def fetch_name_profiles(conn: Connection) -> NameProfiles:
    """Renvoie les profils des personnes à rejets et leurs contributions à juger, depuis les contributions sources. Un document rejeté est une publication, ou à défaut le titre normalisé d'enregistrements sources sans publication."""
    rejected_rows = conn.execute(text(_REJECTED_RECORDS_SQL)).all()
    person_ids = sorted({r.person_id for r in rejected_rows})
    persons = {
        r.id: r
        for r in conn.execute(
            text(
                "SELECT id, last_name_normalized AS last, first_name_normalized AS first FROM persons WHERE id = ANY(:p)"
            ),
            {"p": person_ids},
        )
    }
    own_rows = conn.execute(text(_OWN_CONTRIBUTIONS_SQL), {"persons": person_ids}).all()
    by_record: dict[int, list[Row[tuple[object, ...]]]] = defaultdict(list)
    by_publication: dict[int, list[Row[tuple[object, ...]]]] = defaultdict(list)
    for sc in conn.execute(
        text(_SOURCE_CONTRIBUTIONS_SQL),
        {
            "records": [r.record for r in rejected_rows],
            "publications": sorted(
                {r.publication_id for r in own_rows}
                | {r.publication_id for r in rejected_rows if r.publication_id}
            ),
            "last_names": sorted({p.last for p in persons.values()}),
            "large": LARGE_COLLABORATION,
        },
    ):
        by_record[sc.record].append(sc)
        if sc.publication_id is not None:
            by_publication[sc.publication_id].append(sc)

    # Documents rejetés : une publication, sinon le titre normalisé d'enregistrements sources sans publication.
    rejected_documents: dict[tuple[int, object], _Document] = {}
    pseudo_ids: dict[str, int] = {}
    for r in rejected_rows:
        if r.publication_id is not None:
            key: tuple[int, object] = (r.person_id, r.publication_id)
            if key not in rejected_documents:
                rejected_documents[key] = _Document(
                    r.publication_id,
                    r.person_id,
                    by_publication[r.publication_id],
                    frozenset(),
                    r.serial_id,
                    r.year,
                )
        else:
            key = (r.person_id, r.title_normalized)
            if key not in rejected_documents:
                pseudo = pseudo_ids.setdefault(r.title_normalized, -(len(pseudo_ids) + 1))
                rejected_documents[key] = _Document(
                    pseudo, r.person_id, [], frozenset(), r.serial_id, r.year
                )
            rejected_documents[key].source_contributions.extend(by_record[r.record])
    documents = [
        replace(
            d,
            own=frozenset(
                sc.id
                for sc in d.source_contributions
                if names_compatible(
                    sc.last, sc.first, persons[d.person_id].last, persons[d.person_id].first
                )
            ),
        )
        for d in rejected_documents.values()
    ]
    own_documents = [
        (
            r,
            _Document(
                r.publication_id,
                r.person_id,
                by_publication[r.publication_id],
                frozenset(r.own_source_contributions),
                r.serial_id,
                r.year,
            ),
        )
        for r in own_rows
    ]

    structures: dict[int, list[tuple[str, int]]] = defaultdict(list)
    own_ids = sorted(
        {i for d in documents for i in d.own} | {i for _, d in own_documents for i in d.own}
    )
    for s in conn.execute(
        text(_STRUCTURES_SQL),
        {
            "ids": own_ids,
            "labo": StructureType.LABO.value,
            "hal_types": sorted(CLUE_HAL_STRUCTURE_TYPES),
        },
    ):
        structures[s.source_contribution_id].append((s.kind, s.structure))

    def key_of(person_id: int) -> tuple[str, str]:
        return coauthor_key(persons[person_id].last, persons[person_id].first)

    rejected: dict[int, list[ContributionContext]] = defaultdict(list)
    for d in documents:
        rejected[d.person_id].append(_context(d, key_of(d.person_id), structures))
    own: dict[int, list[ContributionContext]] = defaultdict(list)
    candidates: list[tuple[int, int, ContributionContext]] = []
    for r, d in own_documents:
        context = _context(d, key_of(r.person_id), structures)
        if not r.tie_break:
            own[r.person_id].append(context)
        if r.candidate:
            candidates.append((r.id, r.person_id, context))
    return NameProfiles(dict(own), dict(rejected), candidates)


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
