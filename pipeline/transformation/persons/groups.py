"""Tâche `persons.resolve_groups` : rattache à une personne les groupes de contributions sources qui n'en ont pas (`domain.persons.group_matching`).

Les épinglages s'appliquent d'abord : un groupe dont un membre est épinglé prend la personne épinglée (`pinned_groups_sql`). Un groupe déjà rattaché garde sinon sa personne : `author_grouping` vide la personne d'un groupe dont les membres changent. Sont décidés les groupes sans personne qui ont un membre du périmètre, un membre épinglé, ou un membre dont un identifiant fiable est attribué à une personne. La tâche ne crée pas de personne : un groupe dont la décision est une création reste sans personne.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.persons.group_matching import (
    IDENTIFIER_ORDER,
    GroupDecision,
    GroupMember,
    GroupOutcome,
    PersonIndex,
    decide_group,
    identifiers_to_attribute,
    settle_publication,
)
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.matching import Namesake
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import (
    pinned,
    pinned_groups_sql,
    strong_identifier_source_contributions,
    usable_identifier,
)
from pipeline.transformation.persons.person_writes import add_identifiers_from_contributions
from pipeline.transformation.persons.store import (
    PersonsStore,
    fetch_identifier_to_person_map,
    fetch_name_form_map,
    fetch_name_form_status_map,
    fetch_rejected_person_ids_by_publication,
)

_CANDIDATES_SQL = " UNION ".join(
    [
        f"""
        SELECT g.id AS group_id
        FROM source_contribution_groups g
        JOIN source_contribution_group_members gm ON gm.group_id = g.id
        JOIN source_contributions sc ON sc.id = gm.source_contribution_id
        WHERE g.person_id IS NULL AND (sc.in_perimeter OR {pinned("sc.id")})
        """,
        *(
            strong_identifier_source_contributions(
                id_type,
                identifiers="person_identifiers",
                select="gm.group_id",
                joins="""
                    JOIN source_contribution_group_members gm ON gm.source_contribution_id = sc_auth.id
                    JOIN source_contribution_groups g ON g.id = gm.group_id
                """,
                where=f"g.person_id IS NULL AND pi.status <> '{AttributionStatus.REJECTED.value}'",
            )
            for id_type in IDENTIFIER_ORDER
        ),
    ]
)

_IDENTIFIERS_OBJECT = ", ".join(
    f"'{t.value}', {usable_identifier(repr(t.value), source_contribution='sc')}"
    for t in PersonIdentifierType
)

_MEMBERS_SQL = f"""
    SELECT g.id AS group_id, g.publication_id, sc.source::text AS source,
           sc.raw_author_name, sc.raw_last_name, sc.raw_first_name,
           jsonb_strip_nulls(jsonb_build_object({_IDENTIFIERS_OBJECT})) AS identifiers,
           sc.in_perimeter, sc.roles,
           (SELECT ca.person_id FROM confirmed_source_contributions ca
            WHERE ca.source_contribution_id = sc.id) AS pinned_person_id
    FROM ({_CANDIDATES_SQL}) c
    JOIN source_contribution_groups g ON g.id = c.group_id
    JOIN source_contribution_group_members gm ON gm.group_id = g.id
    JOIN source_contributions sc ON sc.id = gm.source_contribution_id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
    ORDER BY g.id
"""

# Personnes déjà rattachées à un groupe, par publication.
_TAKEN_SQL = """
    SELECT publication_id, array_agg(person_id) AS person_ids
    FROM source_contribution_groups
    WHERE person_id IS NOT NULL AND publication_id = ANY(:publications)
    GROUP BY publication_id
"""

_WRITE_SQL = text("""
    UPDATE source_contribution_groups g
    SET person_id = u.person_id, resolution_mode = CAST(u.mode AS group_resolution_mode)
    FROM unnest(CAST(:ids AS integer[]), CAST(:persons AS integer[]), CAST(:modes AS text[]))
        AS u(id, person_id, mode)
    WHERE g.id = u.id AND g.person_id IS NULL
""")


def load_index(conn: Connection) -> PersonIndex:
    """Index complet des personnes : identifiants attribués, formes de nom, verdicts des formes, homonymes par nom de famille."""
    namesakes: dict[str, list[Namesake]] = defaultdict(list)
    for namesake in PersonsStore(conn).namesakes():
        namesakes[normalize_text(namesake.last_name)].append(namesake)
    return PersonIndex(
        identifiers={t: fetch_identifier_to_person_map(conn, t) for t in IDENTIFIER_ORDER},
        name_forms=fetch_name_form_map(conn),
        name_form_status=fetch_name_form_status_map(conn),
        namesakes=namesakes,
    )


def load_candidate_groups(conn: Connection) -> dict[int, dict[int, list[GroupMember]]]:
    """Membres des groupes à décider, par publication puis par groupe."""
    groups: dict[int, dict[int, list[GroupMember]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute(text(_MEMBERS_SQL)):
        groups[r.publication_id][r.group_id].append(
            GroupMember(
                source=r.source,
                name=ContributorName.from_columns(
                    r.raw_author_name, r.raw_last_name, r.raw_first_name
                ),
                identifiers=r.identifiers,
                in_perimeter=r.in_perimeter,
                roles=r.roles or (),
                pinned_person_id=r.pinned_person_id,
            )
        )
    return groups


def taken_persons(conn: Connection, publication_ids: Iterable[int]) -> dict[int, frozenset[int]]:
    """Personnes déjà rattachées à un groupe de chaque publication."""
    rows = conn.execute(text(_TAKEN_SQL), {"publications": list(publication_ids)})
    return {r.publication_id: frozenset(r.person_ids) for r in rows}


def decide_groups(
    groups: dict[int, dict[int, list[GroupMember]]],
    index: PersonIndex,
    rejected: dict[int, frozenset[int]],
    taken: dict[int, frozenset[int]],
) -> dict[int, GroupDecision]:
    """Décision de chaque groupe, une personne au plus par publication."""
    decisions: dict[int, GroupDecision] = {}
    for publication_id, by_group in groups.items():
        rejected_here = rejected.get(publication_id, frozenset())
        decided = {
            group_id: (decide_group(members, index, rejected_here), len(members))
            for group_id, members in by_group.items()
        }
        decisions |= settle_publication(decided, taken.get(publication_id, frozenset()))
    return decisions


def write_decisions(conn: Connection, decisions: dict[int, GroupDecision]) -> int:
    """Écrit la personne et le mode des groupes rattachés. Rend le nombre de groupes écrits."""
    matched = [
        (group_id, d.person_id, str(d.reason))
        for group_id, d in decisions.items()
        if d.outcome == GroupOutcome.MATCH
    ]
    if not matched:
        return 0
    ids, persons, modes = zip(*matched, strict=True)
    return conn.execute(
        _WRITE_SQL, {"ids": list(ids), "persons": list(persons), "modes": list(modes)}
    ).rowcount


def attribute_identifiers(
    conn: Connection,
    groups: dict[int, dict[int, list[GroupMember]]],
    decisions: dict[int, GroupDecision],
) -> None:
    """Attribue en attente, à la personne de chaque groupe rattaché par la décision, les identifiants fiables de ses membres (`identifiers_to_attribute`)."""
    members_by_group = {
        group_id: members for by_group in groups.values() for group_id, members in by_group.items()
    }
    repo = PgPersonRepository(conn)
    for group_id, decision in decisions.items():
        if decision.outcome != GroupOutcome.MATCH or decision.person_id is None:
            continue
        add_identifiers_from_contributions(
            decision.person_id,
            identifiers_to_attribute(members_by_group[group_id], decision),
            repo=repo,
        )


def apply_pins(conn: Connection) -> int:
    """Rattache à la personne épinglée les groupes dont un membre est épinglé (`pinned_groups_sql`). Rend le nombre de groupes rattachés."""
    release, attach = pinned_groups_sql("SELECT id FROM source_contribution_groups")
    conn.execute(text(release))
    return conn.execute(text(attach)).rowcount


def resolve_groups(conn: Connection) -> dict[str, int]:
    """Applique les épinglages, puis décide et écrit la personne des groupes sans personne. Rend les compteurs par issue et par motif."""
    pinned = apply_pins(conn)
    groups = load_candidate_groups(conn)
    decisions = decide_groups(
        groups,
        load_index(conn),
        fetch_rejected_person_ids_by_publication(conn),
        taken_persons(conn, groups),
    )
    written = write_decisions(conn, decisions)
    attribute_identifiers(conn, groups, decisions)
    counts: Counter[str] = Counter(
        f"{d.outcome}:{d.reason}" if d.reason is not None else str(d.outcome)
        for d in decisions.values()
    )
    return {"pinned": pinned, "groups": len(decisions), "written": written, **counts}
