"""Tâche `persons.resolve_groups` : rattache à une personne les groupes de contributions sources qui n'en ont pas (`domain.persons.group_matching`).

Les épinglages s'appliquent d'abord : un groupe dont un membre est épinglé prend la personne épinglée (`pinned_groups_sql`). Un groupe déjà rattaché garde sinon sa personne : `author_grouping` vide la personne d'un groupe dont les membres changent. Sont décidés les groupes sans personne qui ont un membre du périmètre, un membre épinglé, ou un membre dont un identifiant fiable est attribué à une personne. Les groupes du périmètre au nom inconnu sont traités ensuite, un à un, contre l'index tenu à jour : un groupe rejoint une personne créée plus tôt dans le passage, ou fonde la sienne (`create_persons`).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable

from sqlalchemy import Connection, text

from domain.errors import ValidationError
from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.persons.group_matching import (
    IDENTIFIER_ORDER,
    GroupDecision,
    GroupMatchReason,
    GroupMember,
    GroupOutcome,
    GroupSkipReason,
    PersonIndex,
    decide_group,
    founding_name,
    identifiers_to_attribute,
    settle_publication,
)
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.matching import Namesake
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person import validated_name
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import (
    GROUP_MEMBERS,
    pinned,
    pinned_groups_sql,
    strong_identifier_source_contributions,
    usable_identifier,
)
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    quantity,
    step,
)
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger
from pipeline.runtime.observability.progress import Progress, track_progress, waiting
from pipeline.transformation.persons.first_names import complete_reduced_first_names
from pipeline.transformation.persons.person_writes import add_identifiers_from_contributions
from pipeline.transformation.persons.store import (
    fetch_identifier_to_person_map,
    fetch_name_form_map,
    fetch_name_form_status_map,
    fetch_namesakes,
    fetch_rejected_person_ids_by_publication,
)

_CANDIDATES_SQL = " UNION ".join(
    [
        f"""
        SELECT g.id AS group_id
        FROM {GROUP_MEMBERS}
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
    FROM {GROUP_MEMBERS}
    JOIN ({_CANDIDATES_SQL}) c ON c.group_id = g.id
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


def load_index(conn: Connection, conflicting: frozenset[int] = frozenset()) -> PersonIndex:
    """Index complet des personnes : identifiants attribués, formes de nom, verdicts des formes, homonymes par nom de famille. `conflicting` : personnes au prénom réduit dont les groupes attestent plusieurs prénoms pleins (`Namesake.conflicting`)."""
    namesakes: dict[str, list[Namesake]] = defaultdict(list)
    for namesake in fetch_namesakes(conn):
        namesakes[normalize_text(namesake.last_name)].append(
            namesake._replace(conflicting=namesake.person_id in conflicting)
        )
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
    progress: Progress | None = None,
) -> dict[int, GroupDecision]:
    """Décision de chaque groupe, une personne au plus par publication. `progress` avance d'un groupe décidé et retient les groupes rattachés."""
    decisions: dict[int, GroupDecision] = {}
    for publication_id, by_group in groups.items():
        rejected_here = rejected.get(publication_id, frozenset())
        decided = {
            group_id: (decide_group(members, index, rejected_here), len(members))
            for group_id, members in by_group.items()
        }
        settled = settle_publication(decided, taken.get(publication_id, frozenset()))
        if progress is not None:
            for decision in settled.values():
                progress.advance()
                if decision.outcome == GroupOutcome.MATCH:
                    progress.keep()
        decisions |= settled
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


def create_persons(
    conn: Connection,
    groups: dict[int, dict[int, list[GroupMember]]],
    decisions: dict[int, GroupDecision],
    index: PersonIndex,
    rejected: dict[int, frozenset[int]],
    taken: dict[int, frozenset[int]],
    progress: Progress | None = None,
) -> int:
    """Traite un à un les groupes dont la décision est une création, contre l'index tenu à jour : un groupe que désigne une personne créée plus tôt dans le passage la rejoint ; sinon une personne naît de son nom (`founding_name`), et l'index l'enregistre. Une personne déjà rattachée à un autre groupe de la publication n'est pas reprise. Met `decisions` à jour et rend le nombre de personnes créées. `progress` avance d'un groupe traité et retient les personnes créées."""
    repo = PgPersonRepository(conn)
    created = 0
    for publication_id in sorted(groups):
        by_group = groups[publication_id]
        taken_here = set(taken.get(publication_id, frozenset())) | {
            decisions[group_id].person_id
            for group_id in by_group
            if decisions[group_id].outcome == GroupOutcome.MATCH
        }
        for group_id in sorted(by_group):
            if decisions[group_id].outcome != GroupOutcome.CREATE:
                continue
            members = by_group[group_id]
            if progress is not None:
                progress.advance()
            decision = decide_group(members, index, rejected.get(publication_id, frozenset()))
            if decision.outcome == GroupOutcome.CREATE:
                try:
                    last_name, first_name = validated_name(*founding_name(members))
                except ValidationError:
                    continue
                person_id = repo.create(last_name, first_name)
                repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))
                identifiers = identifiers_to_attribute(members, decision)
                index.register(
                    person_id,
                    last_name,
                    first_name,
                    {k: v for attributed in identifiers for k, v in attributed.items()},
                )
                created += 1
                if progress is not None:
                    progress.keep()
                decision = GroupDecision(
                    GroupOutcome.CREATE,
                    person_id,
                    GroupMatchReason.NAME,
                    decision.evidence,
                    decision.refused,
                )
            elif decision.outcome == GroupOutcome.MATCH and decision.person_id in taken_here:
                decision = GroupDecision(
                    GroupOutcome.SKIP,
                    reason=GroupSkipReason.PERSON_IN_OTHER_GROUP,
                    evidence=decision.evidence,
                    refused=decision.refused,
                )
            decisions[group_id] = decision
            if decision.person_id is None or decision.outcome == GroupOutcome.SKIP:
                continue
            conn.execute(
                _WRITE_SQL,
                {
                    "ids": [group_id],
                    "persons": [decision.person_id],
                    "modes": [str(decision.reason)],
                },
            )
            add_identifiers_from_contributions(
                decision.person_id, identifiers_to_attribute(members, decision), repo=repo
            )
            taken_here.add(decision.person_id)
    return created


def apply_pins(conn: Connection) -> int:
    """Rattache à la personne épinglée les groupes dont un membre est épinglé (`pinned_groups_sql`). Rend le nombre de groupes rattachés."""
    release, attach = pinned_groups_sql("SELECT id FROM source_contribution_groups")
    conn.execute(text(release))
    return conn.execute(text(attach)).rowcount


# Libellés des modes de rattachement dans le journal.
_MODE_LABELS: dict[GroupMatchReason, str] = {
    GroupMatchReason.MANUAL: "par épinglage",
    GroupMatchReason.ORCID: "par ORCID",
    GroupMatchReason.HAL_PERSON_ID: "par compte HAL",
    GroupMatchReason.IDREF: "par IdRef",
    GroupMatchReason.NAME: "par nom sans homonymie",
    GroupMatchReason.COMPATIBLE_NAME: "par initiales compatibles",
}


def _log_identified(
    logger: ScopedOrPlainLogger, decisions: dict[int, GroupDecision], pinned: int
) -> None:
    """Contributions identifiées, mode de rattachement par mode de rattachement, nombres alignés à droite. Les épinglages appliqués avant la décision comptent avec le mode `manual`."""
    by_mode: Counter[GroupMatchReason] = Counter(
        d.reason
        for d in decisions.values()
        if d.outcome == GroupOutcome.MATCH and isinstance(d.reason, GroupMatchReason)
    )
    by_mode[GroupMatchReason.MANUAL] += pinned
    total = sum(by_mode.values())
    logger.info(
        "%s%s %s, dont", LAST_BRANCH, quantity(total, "contribution"), inflect(total, "identifiée")
    )
    width = max(len(str(by_mode[mode])) for mode in _MODE_LABELS)
    logger.info("")
    for mode, label in _MODE_LABELS.items():
        logger.info("     %s %s", str(by_mode[mode]).rjust(width), label)


def resolve_groups(conn: Connection, logger: ScopedOrPlainLogger) -> dict[str, int]:
    """Applique les épinglages, complète les prénoms réduits (`complete_reduced_first_names`), décide et écrit la personne des groupes sans personne, puis crée les personnes des groupes du périmètre au nom inconnu (`create_persons`). Rend les compteurs par issue et par motif."""
    pinned = apply_pins(conn)
    completion = complete_reduced_first_names(conn, repo=PgPersonRepository(conn))
    logger.info(
        "%s%s d'après les contributions",
        BRANCH,
        quantity(completion.completed, "prénom complété", "prénoms complétés"),
    )
    # Le chargement dure : la ligne d'attente évite que l'étape reste muette.
    with waiting(f"{BRANCH}chargement des contributions", logger) as line:
        groups = load_candidate_groups(conn)
        index = load_index(conn, completion.conflicting)
        rejected = fetch_rejected_person_ids_by_publication(conn)
        taken = taken_persons(conn, groups)
        total = sum(len(by_group) for by_group in groups.values())
        line.conclude(f"{BRANCH}{quantity(total, 'contribution')} à examiner")
    with track_progress(total, BRANCH.rstrip(), logger, count_kept=True) as progress:
        decisions = decide_groups(groups, index, rejected, taken, progress)
    written = write_decisions(conn, decisions)
    attribute_identifiers(conn, groups, decisions)
    _log_identified(logger, decisions, pinned)

    step(logger, "Création de nouvelles personnes")
    unidentified = [
        d
        for d in decisions.values()
        if d.outcome != GroupOutcome.MATCH and d.reason != GroupSkipReason.OUT_OF_PERIMETER
    ]
    to_create = sum(1 for d in unidentified if d.outcome == GroupOutcome.CREATE)
    undecidable = sum(
        1
        for d in unidentified
        if d.outcome == GroupOutcome.SKIP and d.reason != GroupSkipReason.CREATION_NOT_ALLOWED
    )
    logger.info(
        "%s%s du périmètre %s",
        BRANCH,
        quantity(len(unidentified), "contribution"),
        inflect(len(unidentified), "non identifiée"),
    )
    logger.info(
        "%s%s (nom ambigu, noms ou identifiants en conflit, candidats rejetés)",
        BRANCH,
        quantity(undecidable, "indécidable"),
    )
    with track_progress(to_create, BRANCH.rstrip(), logger, count_kept=True) as progress:
        created = create_persons(conn, groups, decisions, index, rejected, taken, progress)
    logger.info("%s%s %s", LAST_BRANCH, quantity(created, "personne"), inflect(created, "créée"))
    counts: Counter[str] = Counter(
        f"{d.outcome}:{d.reason}" if d.reason is not None else str(d.outcome)
        for d in decisions.values()
    )
    return {
        "pinned": pinned,
        "first_names_completed": completion.completed,
        "groups": len(decisions),
        "written": written,
        "created": created,
        **counts,
    }
