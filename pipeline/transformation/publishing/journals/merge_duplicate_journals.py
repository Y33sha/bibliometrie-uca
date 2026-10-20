"""Sous-étape de la phase `publishers_journals` — fusionne les revues en double.

Cinq règles désignent la même publication :

1. deux revues vérifiées dans le Sudoc partagent leur ISSN-L ;
2. le même ISSN est actif dans les deux, et les mots d'un titre sont tous dans l'autre (« BMJ » et « BMJ-BRITISH MEDICAL JOURNAL ») ;
3. vérifiées dans le Sudoc, l'une a, inactif, un ISSN actif dans l'autre : titre précédent ou suivant de la même revue, supplément. La revue dont le premier document est le plus tardif absorbe l'autre : un titre suivant n'a pas de document antérieur à son changement de titre ;
4. elles sont seules à avoir leur titre normalisé, au moins une est sans ISSN, et leurs enregistrements partagent un préfixe DOI ;
5. des enregistrements d'une même publication y sont rattachés, leurs titres sont compatibles (« Phys.Rev.Lett. » et « Physical Review Letters », voir `compatible_titles`), et elles n'ont pas chacune des ISSN sans aucun en commun.

L'éditeur ne sert pas de contrôle : deux fiches d'éditeur désignent souvent la même maison. La fusion elle-même est celle de l'administration des revues, injectée par le composition-root : publications, métadonnées et ISSN passent à la cible, qui requalifie les publications absorbées, puis la source est supprimée. Le journal garde le titre, l'éditeur et les ISSN des deux revues.
"""

import logging
from collections.abc import Callable, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.journals.titles import compatible_titles, nested_titles
from infrastructure.sql_fragments import active_issns, has_active_issn
from pipeline.runtime.observability.libelles import BRANCHE, accord
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression
from pipeline.transformation.publishing.journals.journal_label import journal_label
from pipeline.transformation.publishing.journals.store import JournalStore

LIBELLE = "Fusion des revues en double"
"""Libellé de la sous-étape dans le journal de la phase."""

MergeJournals = Callable[[int, int], None]
"""`(cible, source)` : fusionne la revue source dans la cible et valide la transaction."""

MergeGroup = tuple[str, tuple[int, ...]]
"""`(libellé, revues)` : ce que les revues partagent, puis les revues, la cible en tête."""

# Ce que les revues d'un groupe partagent : la ligne qui annonce chaque règle, au-dessus de sa barre d'avancement.
_REGLES = (
    "même ISSN-L",
    "même ISSN et titre emboîté",
    "titre successif ou supplément",
    "mêmes titre et préfixe DOI",
    "même publication et titre compatible",
)


class JournalMergeGroup(NamedTuple):
    """Revues en double. La cible de la fusion vient en premier."""

    key: str
    """Ce que les revues partagent : ISSN-L ou titre normalisé."""
    journal_ids: tuple[int, ...]


class JournalTitleRow(NamedTuple):
    """Une revue et son titre."""

    id: int
    title: str


class JournalIssnGroup(NamedTuple):
    """Revues où le même ISSN est actif. La cible de la fusion vient en premier."""

    issn: str
    journals: tuple[JournalTitleRow, ...]


class JournalMergeCandidate(NamedTuple):
    """Une revue candidate à une fusion, avec ce qui départage la cible."""

    id: int
    title: str
    issns: frozenset[str]
    """ISSN actifs."""
    pub_count: int


class JournalPublicationPair(NamedTuple):
    """Deux revues auxquelles sont rattachés des enregistrements d'une même publication."""

    first: JournalMergeCandidate
    second: JournalMergeCandidate
    publications: int
    """Nombre de publications communes."""


# Revues aux ISSN établis : tous vérifiés dans le Sudoc, ou saisis à la main.
_VERIFIED = """
    verifiees AS (
        SELECT i.journal_id AS id FROM journal_issns i
        JOIN journals j ON j.id = i.journal_id
        GROUP BY i.journal_id
        HAVING bool_and(i.sudoc_checked_at IS NOT NULL) OR bool_or('issns' = ANY(j.manual_fields))
    )
"""

# Revues vérifiées qui partagent leur ISSN-L, la cible de la fusion en tête de chaque groupe.
_JOURNALS_SHARING_ISSNL = text(f"""
    WITH {_VERIFIED}
    SELECT i.issn AS issnl, array_agg(j.id ORDER BY j.pub_count DESC, j.id) AS ids
    FROM journal_issns i
    JOIN verifiees v ON v.id = i.journal_id
    JOIN journals j ON j.id = i.journal_id
    WHERE i.linking
    GROUP BY i.issn
    HAVING count(*) > 1
    ORDER BY i.issn
""")


# Revues vérifiées où le même ISSN est actif, la cible de la fusion en tête.
_JOURNALS_SHARING_ACTIVE_ISSN = text(f"""
    WITH {_VERIFIED}
    SELECT i.issn,
           array_agg(j.id ORDER BY j.pub_count DESC, j.id) AS ids,
           array_agg(j.title ORDER BY j.pub_count DESC, j.id) AS titles
    FROM journal_issns i
    JOIN verifiees v ON v.id = i.journal_id
    JOIN journals j ON j.id = i.journal_id
    WHERE i.status = 'active'
    GROUP BY i.issn
    HAVING count(*) > 1
    ORDER BY i.issn
""")


# Paires de revues vérifiées dont l'une a, inactif, un ISSN actif dans l'autre. La cible de la fusion en tête : la
# revue dont le premier document est le plus tardif, puis celle qui a le plus de publications.
_JOURNALS_SHARING_AN_INACTIVE_ISSN = text(f"""
    WITH {_VERIFIED}, paires AS (
        SELECT DISTINCT a.issn, least(a.journal_id, b.journal_id) AS x_id,
               greatest(a.journal_id, b.journal_id) AS y_id
        FROM journal_issns a
        JOIN verifiees va ON va.id = a.journal_id
        JOIN journal_issns b ON b.issn = a.issn AND b.journal_id <> a.journal_id
        JOIN verifiees vb ON vb.id = b.journal_id
        WHERE a.status NOT IN ('active', 'malformed') AND b.status = 'active'
    ), revues AS (
        SELECT j.id, j.pub_count,
               (SELECT min(s.pub_year) FROM source_publications s WHERE s.journal_id = j.id)
                   AS premiere_annee
        FROM journals j
        WHERE j.id IN (SELECT x_id FROM paires UNION SELECT y_id FROM paires)
    )
    SELECT p.issn,
           (SELECT array_agg(r.id ORDER BY r.premiere_annee DESC NULLS LAST, r.pub_count DESC, r.id)
            FROM revues r WHERE r.id IN (p.x_id, p.y_id)) AS ids
    FROM paires p
    ORDER BY p.issn
""")

# Paires de revues seules à avoir leur titre, dont au moins une sans ISSN, et dont les
# enregistrements partagent un préfixe DOI. La cible de la fusion en tête. Un titre normalisé vide
# (alphabet non latin, symboles) ne rapproche aucune revue.
_SAME_TITLE_DUPLICATES = text(f"""
    WITH prefixes AS (
        SELECT journal_id AS id, array_agg(DISTINCT split_part(doi, '/', 1)) AS pfx
        FROM source_publications
        WHERE journal_id IS NOT NULL AND doi IS NOT NULL
        GROUP BY journal_id
    ), paires_de_titre AS (
        SELECT title_normalized FROM journals
        WHERE title_normalized <> ''
        GROUP BY title_normalized
        HAVING count(*) = 2
    ), revues AS (
        SELECT j.id, j.title_normalized, j.pub_count,
               {has_active_issn("j.id")} AS a_issn,
               p.pfx
        FROM journals j
        JOIN paires_de_titre USING (title_normalized)
        JOIN prefixes p ON p.id = j.id
    )
    SELECT x.title_normalized,
           (SELECT array_agg(r.id ORDER BY r.pub_count DESC, r.a_issn DESC, r.id)
            FROM revues r WHERE r.id IN (x.id, y.id)) AS ids
    FROM revues x
    JOIN revues y ON y.title_normalized = x.title_normalized AND x.id < y.id
    WHERE NOT (x.a_issn AND y.a_issn) AND x.pfx && y.pfx
    ORDER BY x.title_normalized
""")

# Paires de revues auxquelles sont rattachés les enregistrements d'une même publication, les plus partagées en tête.
_JOURNALS_SHARING_A_PUBLICATION = text(f"""
    WITH rattachements AS (
        SELECT DISTINCT publication_id, journal_id
        FROM source_publications
        WHERE publication_id IS NOT NULL AND journal_id IS NOT NULL
    ), paires AS (
        SELECT a.journal_id AS first_id, b.journal_id AS second_id, count(*) AS publications
        FROM rattachements a
        JOIN rattachements b ON b.publication_id = a.publication_id AND a.journal_id < b.journal_id
        GROUP BY a.journal_id, b.journal_id
    )
    SELECT p.publications,
           x.id AS first_id, x.title AS first_title, x.pub_count AS first_pub_count,
           {active_issns("x.id")} AS first_issns,
           y.id AS second_id, y.title AS second_title, y.pub_count AS second_pub_count,
           {active_issns("y.id")} AS second_issns
    FROM paires p
    JOIN journals x ON x.id = p.first_id
    JOIN journals y ON y.id = p.second_id
    ORDER BY p.publications DESC, p.first_id, p.second_id
""")


def find_journals_sharing_issnl(conn: Connection) -> list[JournalMergeGroup]:
    """Groupes de revues vérifiées dans le Sudoc qui partagent leur ISSN-L. La revue qui a le plus de publications vient en premier, puis la plus petite par identifiant."""
    return [
        JournalMergeGroup(r.issnl, tuple(r.ids))
        for r in conn.execute(_JOURNALS_SHARING_ISSNL).all()
    ]


def find_journals_sharing_active_issn(conn: Connection) -> list[JournalIssnGroup]:
    """Groupes de revues vérifiées dans le Sudoc où le même ISSN est actif, dans le même ordre."""
    return [
        JournalIssnGroup(
            r.issn, tuple(JournalTitleRow(i, t) for i, t in zip(r.ids, r.titles, strict=True))
        )
        for r in conn.execute(_JOURNALS_SHARING_ACTIVE_ISSN).all()
    ]


def find_journals_sharing_an_inactive_issn(conn: Connection) -> list[JournalMergeGroup]:
    """Paires de revues vérifiées dans le Sudoc dont l'une a, inactif, un ISSN actif dans l'autre. La revue dont le premier document est le plus tardif vient en premier, puis celle qui a le plus de publications."""
    return [
        JournalMergeGroup(r.issn, tuple(r.ids))
        for r in conn.execute(_JOURNALS_SHARING_AN_INACTIVE_ISSN).all()
    ]


def find_same_title_duplicates(conn: Connection) -> list[JournalMergeGroup]:
    """Paires de revues seules à avoir leur titre normalisé, dont au moins une sans ISSN, et dont les enregistrements partagent un préfixe DOI. La revue qui a le plus de publications vient en premier, puis celle qui a un ISSN."""
    return [
        JournalMergeGroup(r.title_normalized, tuple(r.ids))
        for r in conn.execute(_SAME_TITLE_DUPLICATES).all()
    ]


def find_journals_sharing_a_publication(conn: Connection) -> list[JournalPublicationPair]:
    """Paires de revues auxquelles sont rattachés les enregistrements d'une même publication. Les paires qui partagent le plus de publications viennent en premier."""
    return [
        JournalPublicationPair(
            JournalMergeCandidate(
                r.first_id, r.first_title, frozenset(r.first_issns), r.first_pub_count
            ),
            JournalMergeCandidate(
                r.second_id, r.second_title, frozenset(r.second_issns), r.second_pub_count
            ),
            r.publications,
        )
        for r in conn.execute(_JOURNALS_SHARING_A_PUBLICATION).all()
    ]


def run_merge_duplicate_journals(
    conn: Connection,
    logger: logging.Logger,
    *,
    merge: MergeJournals,
) -> PhaseMetrics:
    """Applique les cinq règles dans l'ordre. Chaque règle lit ses groupes après les fusions des précédentes."""
    metrics = PhaseMetrics()
    # Revue absorbée → revue qui l'a absorbée. Une revue qui partage ses deux ISSN avec son double figure dans deux groupes.
    absorbed: dict[int, int] = {}
    issnl, issn_et_titre, titre_successif, titre_et_prefixe, publication_et_titre = _REGLES

    def merge_groups(groups: Sequence[MergeGroup], regle: str) -> None:
        if not groups:
            return
        _merge_groups(logger, metrics, JournalStore(conn), merge, absorbed, groups, regle)

    merge_groups(
        [(f"ISSN-L {g.key}", g.journal_ids) for g in find_journals_sharing_issnl(conn)],
        issnl,
    )
    shared = [
        (f"ISSN {g.issn}", tuple(j.id for j in g.journals if _nested(g.journals[0], j)))
        for g in find_journals_sharing_active_issn(conn)
    ]
    merge_groups([(label, ids) for label, ids in shared if len(ids) > 1], issn_et_titre)
    merge_groups(
        [
            (f"ISSN rejeté {g.key}", g.journal_ids)
            for g in find_journals_sharing_an_inactive_issn(conn)
        ],
        titre_successif,
    )
    merge_groups(
        [(f"titre {g.key!r}", g.journal_ids) for g in find_same_title_duplicates(conn)],
        titre_et_prefixe,
    )
    merge_groups(
        _compatible_pairs(find_journals_sharing_a_publication(conn)),
        publication_et_titre,
    )
    if metrics.total:
        metrics.report = accord(
            metrics.extras.get("journals_merged", 0), "revue fusionnée", "revues fusionnées"
        )
    return metrics


def _nested(target: JournalTitleRow, other: JournalTitleRow) -> bool:
    """La cible et la revue candidate ont le même titre, aux mots près."""
    return other.id == target.id or nested_titles(target.title, other.title)


def _compatible_pairs(pairs: Sequence[JournalPublicationPair]) -> list[MergeGroup]:
    """Paires de revues aux titres compatibles, la cible en tête.

    Deux revues qui ont chacune des ISSN, sans aucun en commun, sont deux publications distinctes : « Geosciences » (2076-3263) et « Geosciences » (1023-7429).
    """
    groups: list[MergeGroup] = []
    for pair in pairs:
        a, b = pair.first, pair.second
        if a.issns and b.issns and not a.issns & b.issns:
            continue
        if not compatible_titles(a.title, b.title):
            continue
        target, source = sorted((a, b), key=_merge_priority, reverse=True)
        label = accord(pair.publications, "publication commune", "publications communes")
        groups.append((label, (target.id, source.id)))
    return groups


def _merge_priority(journal: JournalMergeCandidate) -> tuple[bool, int, int]:
    """Rang de cible : la revue qui a un ISSN, puis celle qui a le plus de publications, puis la plus ancienne."""
    return (bool(journal.issns), journal.pub_count, -journal.id)


def _merge_groups(
    logger: logging.Logger,
    metrics: PhaseMetrics,
    journal_store: JournalStore,
    merge: MergeJournals,
    absorbed: dict[int, int],
    groups: Sequence[MergeGroup],
    regle: str,
) -> None:
    """Fusionne chaque groupe dans sa première revue. Une revue déjà absorbée est passée ; une cible déjà absorbée cède la place à celle qui l'a absorbée."""
    metrics.add(seen=len(groups))
    with progression(
        len(groups), f"{BRANCHE}{LIBELLE} ({regle})", logger, efface=True
    ) as avancement:
        for label, journal_ids in groups:
            target = _survivor(journal_ids[0], absorbed)
            sources = [s for s in journal_ids[1:] if s not in absorbed and s != target]
            summaries = journal_store.describe_journals([target, *sources]) if sources else {}
            for source in sources:
                merge(target, source)
                absorbed[source] = target
                metrics.add(journals_merged=1)
                # Ligne de détail : le terminal la masque, le journal la garde.
                logger.info(
                    "%s (%s) : la revue %s absorbe la revue %s",
                    label,
                    regle,
                    journal_label(summaries[target]),
                    journal_label(summaries[source]),
                    extra={"detail": True},
                )
            avancement.avance()


def _survivor(journal_id: int, absorbed: dict[int, int]) -> int:
    """Revue qui subsiste de `journal_id` après les fusions déjà faites."""
    while journal_id in absorbed:
        journal_id = absorbed[journal_id]
    return journal_id
