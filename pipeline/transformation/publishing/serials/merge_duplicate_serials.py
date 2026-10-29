"""Sous-étape de la phase `publishing` — fusionne les revues en double.

Cinq règles désignent la même publication :

1. deux revues vérifiées dans le Sudoc partagent leur ISSN-L ;
2. le même ISSN est actif dans les deux, et les mots d'un titre sont tous dans l'autre (« BMJ » et « BMJ-BRITISH MEDICAL JOURNAL ») ;
3. vérifiées dans le Sudoc, l'une a, inactif, un ISSN actif dans l'autre : titre précédent ou suivant de la même revue, supplément. La revue dont le premier document est le plus tardif absorbe l'autre : un titre suivant n'a pas de document antérieur à son changement de titre ;
4. elles sont seules à avoir leur titre normalisé, au moins une est sans ISSN, et leurs enregistrements partagent un préfixe DOI ;
5. des enregistrements d'une même publication y sont rattachés, leurs titres sont compatibles (« Phys.Rev.Lett. » et « Physical Review Letters », voir `compatible_titles`), et elles n'ont pas chacune des ISSN sans aucun en commun.

L'éditeur ne sert pas de contrôle : deux fiches d'éditeur désignent souvent la même maison. La fusion est celle de l'administration des revues : publications, métadonnées et ISSN passent à la cible, qui requalifie les publications absorbées, puis la source est supprimée. Le journal garde le titre, l'éditeur et les ISSN des deux revues.
"""

import logging
from collections.abc import Callable, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.serials.titles import compatible_titles, nested_titles
from infrastructure.db.source_record_identifiers import serial_doi_sql
from infrastructure.sql_fragments import active_issns, has_active_issn
from pipeline.runtime.observability.log_format import BRANCH, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publishing.serials.serial_label import serial_label
from pipeline.transformation.publishing.serials.store import SerialStore

LABEL = "Fusion des publications en série en double"
"""Libellé de la sous-étape dans le journal de la phase."""

MergeSerials = Callable[[int, int], None]
"""`(cible, source)` : fusionne la revue source dans la cible et valide la transaction."""

MergeGroup = tuple[str, tuple[int, ...]]
"""`(libellé, revues)` : ce que les revues partagent, puis les revues, la cible en tête."""

# Ce que les revues d'un groupe partagent : la ligne qui annonce chaque règle, au-dessus de sa barre d'avancement.
_RULES = (
    "même ISSN-L",
    "même ISSN et titre emboîté",
    "titre successif ou supplément",
    "mêmes titre et préfixe DOI",
    "même publication et titre compatible",
)


class SerialMergeGroup(NamedTuple):
    """Revues en double. La cible de la fusion vient en premier."""

    key: str
    """Ce que les revues partagent : ISSN-L ou titre normalisé."""
    serial_ids: tuple[int, ...]


class SerialTitleRow(NamedTuple):
    """Une revue et son titre."""

    id: int
    title: str


class SerialIssnGroup(NamedTuple):
    """Revues où le même ISSN est actif. La cible de la fusion vient en premier."""

    issn: str
    serials: tuple[SerialTitleRow, ...]


class SerialMergeCandidate(NamedTuple):
    """Une revue candidate à une fusion, avec ce qui départage la cible."""

    id: int
    title: str
    issns: frozenset[str]
    """ISSN actifs."""
    publication_count: int


class SerialPublicationPair(NamedTuple):
    """Deux revues auxquelles sont rattachés des enregistrements d'une même publication."""

    first: SerialMergeCandidate
    second: SerialMergeCandidate
    publications: int
    """Nombre de publications communes."""


# Revues aux ISSN établis : tous vérifiés dans le Sudoc, ou saisis à la main.
_VERIFIED = """
    verifiees AS (
        SELECT i.serial_id AS id FROM serial_issns i
        JOIN serials j ON j.id = i.serial_id
        GROUP BY i.serial_id
        HAVING bool_and(i.sudoc_checked_at IS NOT NULL) OR bool_or('issns' = ANY(j.manual_fields))
    )
"""

# Revues vérifiées qui partagent leur ISSN-L, la cible de la fusion en tête de chaque groupe.
_SERIALS_SHARING_ISSNL = text(f"""
    WITH {_VERIFIED}
    SELECT i.issn AS issnl, array_agg(j.id ORDER BY j.publication_count DESC, j.id) AS ids
    FROM serial_issns i
    JOIN verifiees v ON v.id = i.serial_id
    JOIN serials j ON j.id = i.serial_id
    WHERE i.linking
    GROUP BY i.issn
    HAVING count(*) > 1
    ORDER BY i.issn
""")


# Revues vérifiées où le même ISSN est actif, la cible de la fusion en tête.
_SERIALS_SHARING_ACTIVE_ISSN = text(f"""
    WITH {_VERIFIED}
    SELECT i.issn,
           array_agg(j.id ORDER BY j.publication_count DESC, j.id) AS ids,
           array_agg(j.title ORDER BY j.publication_count DESC, j.id) AS titles
    FROM serial_issns i
    JOIN verifiees v ON v.id = i.serial_id
    JOIN serials j ON j.id = i.serial_id
    WHERE i.status = 'active'
    GROUP BY i.issn
    HAVING count(*) > 1
    ORDER BY i.issn
""")


# Paires de revues vérifiées dont l'une a, inactif, un ISSN actif dans l'autre.
# La cible de la fusion en tête : la revue dont le premier document est le plus tardif, puis celle qui a le plus de publications.
_SERIALS_SHARING_AN_INACTIVE_ISSN = text(f"""
    WITH {_VERIFIED}, paires AS (
        SELECT DISTINCT a.issn, least(a.serial_id, b.serial_id) AS x_id,
               greatest(a.serial_id, b.serial_id) AS y_id
        FROM serial_issns a
        JOIN verifiees va ON va.id = a.serial_id
        JOIN serial_issns b ON b.issn = a.issn AND b.serial_id <> a.serial_id
        JOIN verifiees vb ON vb.id = b.serial_id
        WHERE a.status NOT IN ('active', 'malformed') AND b.status = 'active'
    ), revues AS (
        SELECT j.id, j.publication_count,
               (SELECT min(s.publication_year) FROM source_records s WHERE s.serial_id = j.id)
                   AS premiere_annee
        FROM serials j
        WHERE j.id IN (SELECT x_id FROM paires UNION SELECT y_id FROM paires)
    )
    SELECT p.issn,
           (SELECT array_agg(r.id ORDER BY r.premiere_annee DESC NULLS LAST, r.publication_count DESC, r.id)
            FROM revues r WHERE r.id IN (p.x_id, p.y_id)) AS ids
    FROM paires p
    ORDER BY p.issn
""")

# Paires de revues seules à avoir leur titre, dont au moins une sans ISSN, et dont les enregistrements sources partagent un préfixe DOI. La cible de la fusion en tête.
# Un titre normalisé vide (alphabet non latin, symboles) ne rapproche aucune revue.
_SAME_TITLE_DUPLICATES = text(f"""
    WITH prefixes AS (
        SELECT s.serial_id AS id, array_agg(DISTINCT split_part(d.id_value, '/', 1)) AS pfx
        FROM source_records s
        JOIN source_record_identifiers d ON d.source_record_id = s.id AND {serial_doi_sql("d", "s")}
        WHERE s.serial_id IS NOT NULL
        GROUP BY s.serial_id
    ), paires_de_titre AS (
        SELECT title_normalized FROM serials
        WHERE title_normalized <> ''
        GROUP BY title_normalized
        HAVING count(*) = 2
    ), revues AS (
        SELECT j.id, j.title_normalized, j.publication_count,
               {has_active_issn("j.id")} AS a_issn,
               p.pfx
        FROM serials j
        JOIN paires_de_titre USING (title_normalized)
        JOIN prefixes p ON p.id = j.id
    )
    SELECT x.title_normalized,
           (SELECT array_agg(r.id ORDER BY r.publication_count DESC, r.a_issn DESC, r.id)
            FROM revues r WHERE r.id IN (x.id, y.id)) AS ids
    FROM revues x
    JOIN revues y ON y.title_normalized = x.title_normalized AND x.id < y.id
    WHERE NOT (x.a_issn AND y.a_issn) AND x.pfx && y.pfx
    ORDER BY x.title_normalized
""")

# Paires de revues auxquelles sont rattachés les enregistrements d'une même publication, les plus partagées en tête.
_SERIALS_SHARING_A_PUBLICATION = text(f"""
    WITH rattachements AS (
        SELECT DISTINCT publication_id, serial_id
        FROM source_records
        WHERE publication_id IS NOT NULL AND serial_id IS NOT NULL
    ), paires AS (
        SELECT a.serial_id AS first_id, b.serial_id AS second_id, count(*) AS publications
        FROM rattachements a
        JOIN rattachements b ON b.publication_id = a.publication_id AND a.serial_id < b.serial_id
        GROUP BY a.serial_id, b.serial_id
    )
    SELECT p.publications,
           x.id AS first_id, x.title AS first_title, x.publication_count AS first_publication_count,
           {active_issns("x.id")} AS first_issns,
           y.id AS second_id, y.title AS second_title, y.publication_count AS second_publication_count,
           {active_issns("y.id")} AS second_issns
    FROM paires p
    JOIN serials x ON x.id = p.first_id
    JOIN serials y ON y.id = p.second_id
    ORDER BY p.publications DESC, p.first_id, p.second_id
""")


def find_serials_sharing_issnl(conn: Connection) -> list[SerialMergeGroup]:
    """Groupes de revues vérifiées dans le Sudoc qui partagent leur ISSN-L. La revue qui a le plus de publications vient en premier, puis la plus petite par identifiant."""
    return [
        SerialMergeGroup(r.issnl, tuple(r.ids)) for r in conn.execute(_SERIALS_SHARING_ISSNL).all()
    ]


def find_serials_sharing_active_issn(conn: Connection) -> list[SerialIssnGroup]:
    """Groupes de revues vérifiées dans le Sudoc où le même ISSN est actif, dans le même ordre."""
    return [
        SerialIssnGroup(
            r.issn, tuple(SerialTitleRow(i, t) for i, t in zip(r.ids, r.titles, strict=True))
        )
        for r in conn.execute(_SERIALS_SHARING_ACTIVE_ISSN).all()
    ]


def find_serials_sharing_an_inactive_issn(conn: Connection) -> list[SerialMergeGroup]:
    """Paires de revues vérifiées dans le Sudoc dont l'une a, inactif, un ISSN actif dans l'autre. La revue dont le premier document est le plus tardif vient en premier, puis celle qui a le plus de publications."""
    return [
        SerialMergeGroup(r.issn, tuple(r.ids))
        for r in conn.execute(_SERIALS_SHARING_AN_INACTIVE_ISSN).all()
    ]


def find_same_title_duplicates(conn: Connection) -> list[SerialMergeGroup]:
    """Paires de revues seules à avoir leur titre normalisé, dont au moins une sans ISSN, et dont les enregistrements partagent un préfixe DOI. La revue qui a le plus de publications vient en premier, puis celle qui a un ISSN."""
    return [
        SerialMergeGroup(r.title_normalized, tuple(r.ids))
        for r in conn.execute(_SAME_TITLE_DUPLICATES).all()
    ]


def find_serials_sharing_a_publication(conn: Connection) -> list[SerialPublicationPair]:
    """Paires de revues auxquelles sont rattachés les enregistrements d'une même publication. Les paires qui partagent le plus de publications viennent en premier."""
    return [
        SerialPublicationPair(
            SerialMergeCandidate(
                r.first_id, r.first_title, frozenset(r.first_issns), r.first_publication_count
            ),
            SerialMergeCandidate(
                r.second_id, r.second_title, frozenset(r.second_issns), r.second_publication_count
            ),
            r.publications,
        )
        for r in conn.execute(_SERIALS_SHARING_A_PUBLICATION).all()
    ]


def run_merge_duplicate_serials(
    conn: Connection,
    logger: logging.Logger,
    *,
    merge: MergeSerials,
) -> PhaseMetrics:
    """Applique les cinq règles dans l'ordre. Chaque règle lit ses groupes après les fusions des précédentes."""
    metrics = PhaseMetrics()
    # Revue absorbée → revue qui l'a absorbée. Une revue qui partage ses deux ISSN avec son double figure dans deux groupes.
    absorbed: dict[int, int] = {}
    issnl, issn_and_title, successive_title, title_and_prefix, publication_and_title = _RULES

    def merge_groups(groups: Sequence[MergeGroup], rule: str) -> None:
        if not groups:
            return
        _merge_groups(logger, metrics, SerialStore(conn), merge, absorbed, groups, rule)

    merge_groups(
        [(f"ISSN-L {g.key}", g.serial_ids) for g in find_serials_sharing_issnl(conn)],
        issnl,
    )
    shared = [
        (f"ISSN {g.issn}", tuple(j.id for j in g.serials if _nested(g.serials[0], j)))
        for g in find_serials_sharing_active_issn(conn)
    ]
    merge_groups([(label, ids) for label, ids in shared if len(ids) > 1], issn_and_title)
    merge_groups(
        [
            (f"ISSN rejeté {g.key}", g.serial_ids)
            for g in find_serials_sharing_an_inactive_issn(conn)
        ],
        successive_title,
    )
    merge_groups(
        [(f"titre {g.key!r}", g.serial_ids) for g in find_same_title_duplicates(conn)],
        title_and_prefix,
    )
    merge_groups(
        _compatible_pairs(find_serials_sharing_a_publication(conn)),
        publication_and_title,
    )
    if metrics.total:
        metrics.report = quantity(
            metrics.extras.get("serials_merged", 0), "revue fusionnée", "revues fusionnées"
        )
    return metrics


def _nested(target: SerialTitleRow, other: SerialTitleRow) -> bool:
    """La cible et la revue candidate ont le même titre, aux mots près."""
    return other.id == target.id or nested_titles(target.title, other.title)


def _compatible_pairs(pairs: Sequence[SerialPublicationPair]) -> list[MergeGroup]:
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
        label = quantity(pair.publications, "publication commune", "publications communes")
        groups.append((label, (target.id, source.id)))
    return groups


def _merge_priority(serial: SerialMergeCandidate) -> tuple[bool, int, int]:
    """Rang de cible : la revue qui a un ISSN, puis celle qui a le plus de publications, puis la plus ancienne."""
    return (bool(serial.issns), serial.publication_count, -serial.id)


def _merge_groups(
    logger: logging.Logger,
    metrics: PhaseMetrics,
    serial_store: SerialStore,
    merge: MergeSerials,
    absorbed: dict[int, int],
    groups: Sequence[MergeGroup],
    rule: str,
) -> None:
    """Fusionne chaque groupe dans sa première revue. Une revue déjà absorbée est passée ; une cible déjà absorbée cède la place à celle qui l'a absorbée."""
    metrics.add(seen=len(groups))
    with track_progress(len(groups), f"{BRANCH}{LABEL} ({rule})", logger, erase=True) as progress:
        for label, serial_ids in groups:
            target = _survivor(serial_ids[0], absorbed)
            sources = [s for s in serial_ids[1:] if s not in absorbed and s != target]
            summaries = serial_store.describe_serials([target, *sources]) if sources else {}
            for source in sources:
                merge(target, source)
                absorbed[source] = target
                metrics.add(serials_merged=1)
                # Ligne de détail : le terminal la masque, le journal la garde.
                logger.info(
                    "%s (%s) : la revue %s absorbe la revue %s",
                    label,
                    rule,
                    serial_label(summaries[target]),
                    serial_label(summaries[source]),
                    extra={"detail": True},
                )
            progress.advance()


def _survivor(serial_id: int, absorbed: dict[int, int]) -> int:
    """Revue qui subsiste de `serial_id` après les fusions déjà faites."""
    while serial_id in absorbed:
        serial_id = absorbed[serial_id]
    return serial_id
