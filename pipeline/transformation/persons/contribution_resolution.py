"""Tâche `persons.resolve_contributions` : rattachement des contributions sans personne à une personne (`domain.persons.contribution_matching`).

Les épinglages s'appliquent d'abord : une contribution à contribution source épinglée prend la personne épinglée (`pinned_contributions_sql`). Sinon, une contribution rattachée garde sa personne jusqu'à son entrée dans la file `Queue.CONTRIBUTION_RESOLUTION`. Une contribution entre dans cette file quand ses contributions sources changent, ou quand l'identifiant ou la forme de nom à l'origine du rattachement est invalidé.

Sont décidées :

- les contributions sans personne ayant une contribution source du périmètre, une contribution source épinglée, ou une contribution source à identifiant fiable attribué à une personne ;
- les contributions non manuelles de la file.

Une contribution de la file garde sa personne si sa décision la désigne encore, et la perd sinon. Les contributions du périmètre au nom inconnu sont traitées ensuite, une à une, contre l'index tenu à jour. Chacune rejoint une personne créée dans le même passage, ou fonde la sienne (`create_persons`).
"""

from collections import Counter, defaultdict

from sqlalchemy import Connection, text

from domain.errors import ValidationError
from domain.normalize import normalize_text
from domain.persons.contribution_matching import (
    IDENTIFIER_ORDER,
    AlignedSourceContribution,
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    ContributionSkipReason,
    PersonIndex,
    decide_contribution,
    founding_name,
    identifiers_to_attribute,
    settle_publication,
)
from domain.persons.contributor_name import ContributorName
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.matching import Namesake
from domain.persons.person import validated_name
from domain.publications.contribution_roles import ContributionRole
from infrastructure.db.queues import Queue, delete_processed, snapshot
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import (
    CONTRIBUTIONS_AND_SOURCES,
    DETACHED_CONTRIBUTION,
    pinned_contributions_sql,
    strong_identifier_source_contributions,
    usable_identifier,
)
from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    breakdown,
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

# Relevé de la file des contributions à redécider (`Queue.CONTRIBUTION_RESOLUTION`), pris en début de tâche.
_RESOLUTION_SNAPSHOT = "contribution_resolution_snapshot"

# Contributions à décider, matérialisées en début de tâche.
_CANDIDATES_TABLE = "contribution_resolution_candidates"

# `contributions.in_perimeter` réunit les indices de périmètre de ses contributions sources (`propagate_contribution_attributes_sql`).
_CANDIDATES_SQL = " UNION ".join(
    [
        """
        SELECT id AS contribution_id FROM contributions
        WHERE person_id IS NULL AND in_perimeter
        """,
        """
        SELECT gm.contribution_id
        FROM confirmed_source_contributions ca
        JOIN aligned_source_contributions gm ON gm.source_contribution_id = ca.source_contribution_id
        JOIN contributions g ON g.id = gm.contribution_id
        WHERE g.person_id IS NULL
        """,
        f"""
        SELECT g.id AS contribution_id
        FROM {_RESOLUTION_SNAPSHOT} q
        JOIN contributions g ON g.id = q.id
        WHERE g.resolution_mode IS DISTINCT FROM '{ContributionMatchReason.MANUAL}'
        """,
        *(
            strong_identifier_source_contributions(
                id_type,
                identifiers="person_identifiers",
                select="gm.contribution_id",
                joins="""
                    JOIN aligned_source_contributions gm ON gm.source_contribution_id = sc_auth.id
                    JOIN contributions g ON g.id = gm.contribution_id
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
    SELECT g.id AS contribution_id, g.publication_id, sc.source::text AS source,
           sc.raw_author_name, sc.raw_last_name, sc.raw_first_name,
           jsonb_strip_nulls(jsonb_build_object({_IDENTIFIERS_OBJECT})) AS identifiers,
           sc.in_perimeter, sc.roles,
           (SELECT ca.person_id FROM confirmed_source_contributions ca
            WHERE ca.source_contribution_id = sc.id) AS pinned_person_id
    FROM {CONTRIBUTIONS_AND_SOURCES}
    JOIN {_CANDIDATES_TABLE} c ON c.contribution_id = g.id
    ORDER BY g.id
"""

# Personnes rattachées à une contribution de chaque publication, hors des contributions à décider.
_TAKEN_SQL = """
    SELECT publication_id, array_agg(person_id) AS person_ids
    FROM contributions
    WHERE person_id IS NOT NULL AND publication_id = ANY(:publications) AND id <> ALL(:contributions)
    GROUP BY publication_id
"""

# Seules les contributions dont la personne ou le mode change sont écrites.
_WRITE_SQL = text("""
    UPDATE contributions g
    SET person_id = u.person_id, resolution_mode = CAST(u.mode AS resolution_mode)
    FROM unnest(CAST(:ids AS integer[]), CAST(:persons AS integer[]), CAST(:modes AS text[]))
        AS u(id, person_id, mode)
    WHERE g.id = u.id
      AND (g.person_id, g.resolution_mode::text) IS DISTINCT FROM (u.person_id, u.mode)
""")

# Contributions décidées rattachées à une autre personne que celle désignée par leur décision : elles perdent leur personne.
_RELEASE_SQL = text(f"""
    UPDATE contributions g SET {DETACHED_CONTRIBUTION}
    FROM unnest(CAST(:ids AS integer[]), CAST(:persons AS integer[])) AS u(id, person_id)
    WHERE g.id = u.id AND g.person_id IS NOT NULL AND g.person_id IS DISTINCT FROM u.person_id
""")


def load_index(conn: Connection, conflicting: frozenset[int] = frozenset()) -> PersonIndex:
    """Renvoie l'index complet des personnes : identifiants attribués, formes de nom, verdicts des formes, homonymes par nom de famille.

    Args:
        conflicting: personnes au prénom réduit, auxquelles les contributions donnent plusieurs prénoms pleins (`Namesake.conflicting`).
    """
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


def load_candidate_contributions(
    conn: Connection,
) -> dict[int, dict[int, list[AlignedSourceContribution]]]:
    """Renvoie les contributions sources des contributions à décider, par publication puis par contribution.

    Les contributions à décider sont les contributions sans personne et les contributions non manuelles de la file. La file est relevée (`snapshot`). `resolve_contributions` supprime ensuite de la file les marquages relevés.

    Les contributions à décider sont matérialisées dans une table temporaire analysée : l'estimation de leur nombre guide la jointure avec leurs contributions sources.
    """
    snapshot(conn, Queue.CONTRIBUTION_RESOLUTION, _RESOLUTION_SNAPSHOT)
    conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{_CANDIDATES_TABLE}"))
    conn.execute(text(f"CREATE TEMP TABLE {_CANDIDATES_TABLE} AS {_CANDIDATES_SQL}"))
    conn.execute(text(f"ALTER TABLE {_CANDIDATES_TABLE} ADD PRIMARY KEY (contribution_id)"))
    conn.execute(text(f"ANALYZE {_CANDIDATES_TABLE}"))
    candidates: dict[int, dict[int, list[AlignedSourceContribution]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in conn.execute(text(_MEMBERS_SQL)):
        candidates[r.publication_id][r.contribution_id].append(
            AlignedSourceContribution(
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
    return candidates


def taken_persons(
    conn: Connection, candidates: dict[int, dict[int, list[AlignedSourceContribution]]]
) -> dict[int, frozenset[int]]:
    """Renvoie, pour chaque publication des contributions à décider, les personnes rattachées à une autre contribution."""
    rows = conn.execute(
        text(_TAKEN_SQL),
        {
            "publications": list(candidates),
            "contributions": [
                contribution_id
                for by_contribution in candidates.values()
                for contribution_id in by_contribution
            ],
        },
    )
    return {r.publication_id: frozenset(r.person_ids) for r in rows}


def decide_contributions(
    candidates: dict[int, dict[int, list[AlignedSourceContribution]]],
    index: PersonIndex,
    rejected: dict[int, frozenset[int]],
    taken: dict[int, frozenset[int]],
    progress: Progress | None = None,
) -> dict[int, ContributionDecision]:
    """Renvoie la décision de chaque contribution, avec au maximum une personne par publication.

    Args:
        progress: avance d'une contribution décidée ; retient les contributions rattachées.
    """
    decisions: dict[int, ContributionDecision] = {}
    for publication_id, by_contribution in candidates.items():
        rejected_here = rejected.get(publication_id, frozenset())
        decided = {
            contribution_id: (decide_contribution(members, index, rejected_here), len(members))
            for contribution_id, members in by_contribution.items()
        }
        settled = settle_publication(decided, taken.get(publication_id, frozenset()))
        if progress is not None:
            for decision in settled.values():
                progress.advance()
                if decision.outcome == ContributionOutcome.MATCH:
                    progress.keep()
        decisions |= settled
    return decisions


def release_contributions(conn: Connection, decisions: dict[int, ContributionDecision]) -> int:
    """Retire leur personne aux contributions rattachées par leur décision à une autre personne, à une personne à créer ou à aucune. Précède toute écriture : une publication compte au maximum une personne, et la personne retirée peut revenir à une autre contribution de la publication. Renvoie le nombre de contributions concernées."""
    if not decisions:
        return 0
    return conn.execute(
        _RELEASE_SQL,
        {
            "ids": list(decisions),
            "persons": [
                d.person_id if d.outcome == ContributionOutcome.MATCH else None
                for d in decisions.values()
            ],
        },
    ).rowcount


def write_decisions(conn: Connection, decisions: dict[int, ContributionDecision]) -> int:
    """Écrit la personne et le mode des contributions rattachées, quand ils changent. Renvoie le nombre de contributions écrites."""
    matched = [
        (contribution_id, d.person_id, str(d.reason))
        for contribution_id, d in decisions.items()
        if d.outcome == ContributionOutcome.MATCH
    ]
    if not matched:
        return 0
    ids, persons, modes = zip(*matched, strict=True)
    return conn.execute(
        _WRITE_SQL, {"ids": list(ids), "persons": list(persons), "modes": list(modes)}
    ).rowcount


def attribute_identifiers(
    conn: Connection,
    candidates: dict[int, dict[int, list[AlignedSourceContribution]]],
    decisions: dict[int, ContributionDecision],
) -> None:
    """Attribue en attente, à la personne de chaque contribution rattachée par la décision, les identifiants fiables de ses contributions sources (`identifiers_to_attribute`)."""
    members_by_contribution = {
        contribution_id: members
        for by_contribution in candidates.values()
        for contribution_id, members in by_contribution.items()
    }
    repo = PgPersonRepository(conn)
    for contribution_id, decision in decisions.items():
        if decision.outcome != ContributionOutcome.MATCH or decision.person_id is None:
            continue
        add_identifiers_from_contributions(
            decision.person_id,
            identifiers_to_attribute(members_by_contribution[contribution_id], decision),
            repo=repo,
        )


def create_persons(
    conn: Connection,
    candidates: dict[int, dict[int, list[AlignedSourceContribution]]],
    decisions: dict[int, ContributionDecision],
    index: PersonIndex,
    rejected: dict[int, frozenset[int]],
    taken: dict[int, frozenset[int]],
    progress: Progress | None = None,
) -> int:
    """Traite une à une les contributions à décision de création, contre l'index tenu à jour. Met `decisions` à jour et renvoie le nombre de personnes créées.

    Une contribution désignée par une personne créée dans le même passage rejoint cette personne. Sinon, une personne est créée depuis son nom (`founding_name`) et enregistrée dans l'index. Une personne déjà rattachée à une autre contribution de la publication reste à cette autre contribution.

    Args:
        progress: avance d'une contribution traitée ; retient les personnes créées.
    """
    repo = PgPersonRepository(conn)
    created = 0
    for publication_id in sorted(candidates):
        by_contribution = candidates[publication_id]
        taken_here = set(taken.get(publication_id, frozenset())) | {
            decisions[contribution_id].person_id
            for contribution_id in by_contribution
            if decisions[contribution_id].outcome == ContributionOutcome.MATCH
        }
        for contribution_id in sorted(by_contribution):
            if decisions[contribution_id].outcome != ContributionOutcome.CREATE:
                continue
            members = by_contribution[contribution_id]
            if progress is not None:
                progress.advance()
            decision = decide_contribution(
                members, index, rejected.get(publication_id, frozenset())
            )
            if decision.outcome == ContributionOutcome.CREATE:
                try:
                    last_name, first_name = validated_name(*founding_name(members))
                except ValidationError:
                    continue
                person_id = repo.create(last_name, first_name)
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
                decision = ContributionDecision(
                    ContributionOutcome.CREATE,
                    person_id,
                    ContributionMatchReason.NAME,
                    decision.evidence,
                    decision.refused,
                )
            elif decision.outcome == ContributionOutcome.MATCH and decision.person_id in taken_here:
                decision = ContributionDecision(
                    ContributionOutcome.SKIP,
                    reason=ContributionSkipReason.PERSON_IN_OTHER_CONTRIBUTION,
                    evidence=decision.evidence,
                    refused=decision.refused,
                )
            decisions[contribution_id] = decision
            if decision.person_id is None or decision.outcome == ContributionOutcome.SKIP:
                continue
            conn.execute(
                _WRITE_SQL,
                {
                    "ids": [contribution_id],
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
    """Rattache à la personne épinglée les contributions à contribution source épinglée (`pinned_contributions_sql`). Renvoie le nombre de contributions rattachées."""
    release, attach = pinned_contributions_sql("SELECT id FROM contributions")
    conn.execute(text(release))
    return conn.execute(text(attach)).rowcount


# Libellés des modes de rattachement dans le journal.
_MODE_LABELS: dict[ContributionMatchReason, str] = {
    ContributionMatchReason.MANUAL: "par épinglage",
    ContributionMatchReason.ORCID: "par ORCID",
    ContributionMatchReason.HAL_PERSON_ID: "par compte HAL",
    ContributionMatchReason.IDREF: "par IdRef",
    ContributionMatchReason.NAME: "par nom sans homonymie",
    ContributionMatchReason.COMPATIBLE_NAME: "par initiales compatibles",
}


def _log_identified(
    logger: ScopedOrPlainLogger, decisions: dict[int, ContributionDecision], pinned: int
) -> None:
    """Journalise les contributions identifiées par mode de rattachement, nombres alignés à droite. Les épinglages appliqués avant la décision comptent dans le mode `manual`."""
    by_mode: Counter[ContributionMatchReason] = Counter(
        d.reason
        for d in decisions.values()
        if d.outcome == ContributionOutcome.MATCH and isinstance(d.reason, ContributionMatchReason)
    )
    by_mode[ContributionMatchReason.MANUAL] += pinned
    total = sum(by_mode.values())
    breakdown(
        logger,
        f"{quantity(total, 'contribution')} {inflect(total, 'identifiée')}, dont",
        ((by_mode[mode], label) for mode, label in _MODE_LABELS.items()),
    )


def unidentified_orphans(
    candidates: dict[int, dict[int, list[AlignedSourceContribution]]],
    decisions: dict[int, ContributionDecision],
) -> list[ContributionDecision]:
    """Décisions des contributions laissées sans personne parmi les contributions orphelines : contributions du périmètre, sous un rôle d'auteur."""
    return [
        decisions[contribution_id]
        for by_contribution in candidates.values()
        for contribution_id, members in by_contribution.items()
        if decisions[contribution_id].outcome != ContributionOutcome.MATCH
        and any(m.in_perimeter for m in members)
        and any(ContributionRole.AUTHOR in m.roles for m in members)
    ]


def resolve_contributions(conn: Connection, logger: ScopedOrPlainLogger) -> dict[str, int]:
    """Rattache les contributions aux personnes et crée les personnes manquantes. Renvoie les compteurs par issue et par motif.

    Étapes, dans l'ordre :

    - application des épinglages ;
    - complétion des prénoms réduits (`complete_reduced_first_names`) ;
    - décision des contributions sans personne et des contributions en file ;
    - retrait des personnes non désignées par la décision (`release_contributions`) ;
    - écriture des rattachements ;
    - création des personnes des contributions du périmètre au nom inconnu (`create_persons`).
    """
    pinned = apply_pins(conn)
    completion = complete_reduced_first_names(conn, repo=PgPersonRepository(conn))
    logger.info(
        "%s%s d'après les contributions",
        BRANCH,
        quantity(completion.completed, "prénom complété", "prénoms complétés"),
    )
    # Le chargement est long : une ligne d'attente le signale.
    with waiting(f"{BRANCH}chargement des contributions", logger) as line:
        candidates = load_candidate_contributions(conn)
        index = load_index(conn, completion.conflicting)
        rejected = fetch_rejected_person_ids_by_publication(conn)
        taken = taken_persons(conn, candidates)
        total = sum(len(by_contribution) for by_contribution in candidates.values())
        line.conclude(f"{BRANCH}{quantity(total, 'contribution')} à examiner")
    with track_progress(total, BRANCH.rstrip(), logger, count_kept=True) as progress:
        decisions = decide_contributions(candidates, index, rejected, taken, progress)
    released = release_contributions(conn, decisions)
    written = write_decisions(conn, decisions)
    attribute_identifiers(conn, candidates, decisions)
    _log_identified(logger, decisions, pinned)

    step(logger, "Création de nouvelles personnes")
    unidentified = unidentified_orphans(candidates, decisions)
    undecidable = sum(1 for d in unidentified if d.outcome == ContributionOutcome.SKIP)
    to_create = sum(1 for d in decisions.values() if d.outcome == ContributionOutcome.CREATE)
    logger.info(
        "%s%s d'auteur du périmètre %s",
        BRANCH,
        quantity(len(unidentified), "contribution"),
        inflect(len(unidentified), "non identifiée"),
    )
    logger.info("%s%s", BRANCH, quantity(undecidable, "indécidable"))
    with track_progress(to_create, BRANCH.rstrip(), logger, count_kept=True) as progress:
        created = create_persons(conn, candidates, decisions, index, rejected, taken, progress)
    logger.info("%s%s %s", LAST_BRANCH, quantity(created, "personne"), inflect(created, "créée"))
    delete_processed(conn, Queue.CONTRIBUTION_RESOLUTION, _RESOLUTION_SNAPSHOT)
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
        "released": released,
        **counts,
    }
