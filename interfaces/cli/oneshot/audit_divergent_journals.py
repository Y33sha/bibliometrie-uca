# STATUS: oneshot (2026-09-17)
"""Audit (lecture seule) : publications dont les enregistrements portent des revues différentes selon la source.

Chaque couple (publication, revue A, revue B) reçoit une cause, dans cet ordre :

1. **titre parasite** — un titre de revue porte un volume, un numéro ou un texte étranger à un titre ;
2. **ouvrage** — un côté est une plateforme d'ebooks ou une collection, ou les documents sont des livres ou des chapitres ;
3. **doublon** — les deux revues partagent leur titre normalisé, un ISSN ou une forme de nom, ou leurs titres sont compatibles (`compatible_titles`) ;
4. **dépôt ou preprint** — un côté est un entrepôt ou un serveur de preprints ;
5. **documents réunis à tort** — un côté est sans DOI et les types de document sont disjoints ;
6. **revue erronée** — les deux éditeurs sont connus et un seul répond à l'éditeur du préfixe du DOI ;
7. **indéterminé** — reste le nombre de publications sur lesquelles le couple de revues revient.

Les revues rattachées par le préfixe du DOI (phase `metadata_correction`) sont écartées : seules comptent les revues que les sources donnent.

Le rapport compte les couples par cause et en donne des exemples. Le CSV porte le détail, un couple de revues par ligne.

Usage :
    python -m interfaces.cli.oneshot.audit_divergent_journals
    python -m interfaces.cli.oneshot.audit_divergent_journals --samples 10
    python -m interfaces.cli.oneshot.audit_divergent_journals --csv-out chemin/du/rapport.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from pathlib import Path

from sqlalchemy import Connection, text

from domain.journals.titles import compatible_titles
from domain.publishers.names import publisher_name_key
from infrastructure import PROJECT_ROOT
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_divergent_journals", os.path.dirname(__file__))

_DEFAULT_CSV = PROJECT_ROOT / "data" / "divergent_journals.csv"

_BOOK_DOC_TYPES = frozenset({"book", "book_chapter"})
_BOOK_JOURNAL_TYPES = frozenset({"ebook_platform", "book_series"})
_DEPOSIT_JOURNAL_TYPES = frozenset({"repository", "preprint_server"})

# Un couple de revues porté par au moins autant de publications vient d'un rattachement systématique.
_RECURRENT_MIN = 3

# Volume ou numéro dans un titre : « Physical review / D 103 », « Journal of high energy physics 2018(7) ».
_VOLUME_IN_TITLE = re.compile(r"(/ .*\d|\d+\s*\(\d+\)\s*$|\s\d{2,}\s*$)")
_LONGEST_TITLE = 200

_COLUMNS = (
    "cause",
    "publications",
    "revue_a",
    "titre_a",
    "type_a",
    "issn_a",
    "editeur_a",
    "sources_a",
    "revue_b",
    "titre_b",
    "type_b",
    "issn_b",
    "editeur_b",
    "sources_b",
    "cote_non_conforme",
    "exemple_publication",
    "exemple_doi",
)

# Publications dont les enregistrements portent au moins deux revues, hors rattachement par préfixe DOI.
_DIVERGENT = """
    SELECT publication_id FROM source_publications
    WHERE publication_id IS NOT NULL AND journal_id IS NOT NULL
      AND NOT (raw_metadata ? 'journal_id')
    GROUP BY publication_id HAVING count(DISTINCT journal_id) > 1
"""


class Cause(StrEnum):
    """Cause d'une divergence, telle que l'audit la reconnaît."""

    PARASITE = "titre parasite"
    OUVRAGE = "ouvrage"
    DOUBLON = "doublon"
    DEPOT = "dépôt ou preprint"
    REUNIS = "documents réunis à tort"
    ERRONEE = "revue erronée"
    RECURRENT = "indéterminé, couple récurrent"
    ISOLE = "indéterminé, couple isolé"


@dataclass(frozen=True, slots=True)
class Journal:
    """Revue, avec ce qui sert à la rapprocher d'une autre."""

    title: str
    title_normalized: str
    issns: frozenset[str]
    name_forms: frozenset[str]
    publisher: str
    publisher_key: str
    journal_type: str


@dataclass(frozen=True, slots=True)
class Side:
    """Un côté du couple : la revue, et ce qu'en disent les enregistrements qui la portent."""

    journal: Journal
    sources: frozenset[str]
    doc_types: frozenset[str]
    has_doi: bool


def _is_parasite(journal: Journal) -> bool:
    """Titre qui n'est pas celui d'une revue : volume ou numéro, retour à la ligne, longueur d'un résumé."""
    return (
        "\n" in journal.title
        or len(journal.title) > _LONGEST_TITLE
        or _VOLUME_IN_TITLE.search(journal.title) is not None
    )


def _is_book(a: Side, b: Side) -> bool:
    types = {a.journal.journal_type, b.journal.journal_type}
    return bool((a.doc_types | b.doc_types) & _BOOK_DOC_TYPES) or bool(types & _BOOK_JOURNAL_TYPES)


def _is_duplicate(a: Journal, b: Journal) -> bool:
    return (
        a.title_normalized == b.title_normalized
        or bool(a.issns & b.issns)
        or bool(a.name_forms & b.name_forms)
        or compatible_titles(a.title, b.title)
    )


def _wrong_side(a: Side, b: Side, prefix_publisher: str) -> Side | None:
    """Côté dont l'éditeur diffère de celui du préfixe du DOI, quand l'autre côté lui répond."""
    if not (a.journal.publisher_key and b.journal.publisher_key and prefix_publisher):
        return None
    if (a.journal.publisher_key == prefix_publisher) == (
        b.journal.publisher_key == prefix_publisher
    ):
        return None
    return b if a.journal.publisher_key == prefix_publisher else a


def _cause(a: Side, b: Side, prefix_publisher: str, publications: int) -> Cause:
    """Cause de la divergence, du signal le plus fort au plus faible."""
    if _is_parasite(a.journal) or _is_parasite(b.journal):
        return Cause.PARASITE
    if _is_book(a, b):
        return Cause.OUVRAGE
    if _is_duplicate(a.journal, b.journal):
        return Cause.DOUBLON
    if {a.journal.journal_type, b.journal.journal_type} & _DEPOSIT_JOURNAL_TYPES:
        return Cause.DEPOT
    if a.has_doi != b.has_doi and a.doc_types.isdisjoint(b.doc_types):
        return Cause.REUNIS
    if _wrong_side(a, b, prefix_publisher) is not None:
        return Cause.ERRONEE
    return Cause.RECURRENT if publications >= _RECURRENT_MIN else Cause.ISOLE


def _fetch_journals(conn: Connection) -> dict[int, Journal]:
    name_forms: defaultdict[int, set[str]] = defaultdict(set)
    for row in conn.execute(text("SELECT journal_id, form_normalized FROM journal_name_forms")):
        name_forms[row.journal_id].add(row.form_normalized)
    journals: dict[int, Journal] = {}
    rows = conn.execute(
        text("""
            SELECT j.id, j.title, j.title_normalized, j.issn, j.eissn, j.issnl,
                   j.journal_type::text AS journal_type, coalesce(p.name, '') AS publisher
            FROM journals j
            LEFT JOIN publishers p ON p.id = j.publisher_id
        """)
    )
    for row in rows:
        journals[row.id] = Journal(
            title=row.title,
            title_normalized=row.title_normalized,
            issns=frozenset(v for v in (row.issn, row.eissn, row.issnl) if v is not None),
            name_forms=frozenset(name_forms[row.id]),
            publisher=row.publisher,
            publisher_key=publisher_name_key(row.publisher) if row.publisher else "",
            journal_type=row.journal_type,
        )
    return journals


def _fetch_sides(conn: Connection, journals: dict[int, Journal]) -> dict[int, dict[int, Side]]:
    """Par publication, un côté par revue que ses enregistrements portent."""
    rows = conn.execute(
        text(f"""
            SELECT publication_id, journal_id, source::text AS source, doc_type, doi
            FROM source_publications
            WHERE journal_id IS NOT NULL AND NOT (raw_metadata ? 'journal_id')
              AND publication_id IN ({_DIVERGENT})
        """)
    )
    sources: defaultdict[tuple[int, int], set[str]] = defaultdict(set)
    doc_types: defaultdict[tuple[int, int], set[str]] = defaultdict(set)
    with_doi: set[tuple[int, int]] = set()
    for row in rows:
        key = (row.publication_id, row.journal_id)
        sources[key].add(row.source)
        if row.doc_type:
            doc_types[key].add(row.doc_type)
        if row.doi:
            with_doi.add(key)
    sides: defaultdict[int, dict[int, Side]] = defaultdict(dict)
    for key in sources:
        publication_id, journal_id = key
        sides[publication_id][journal_id] = Side(
            journal=journals[journal_id],
            sources=frozenset(sources[key]),
            doc_types=frozenset(doc_types[key]),
            has_doi=key in with_doi,
        )
    return dict(sides)


def _fetch_dois(conn: Connection) -> dict[int, str]:
    rows = conn.execute(
        text(f"SELECT id, doi FROM publications WHERE doi IS NOT NULL AND id IN ({_DIVERGENT})")
    )
    return {row.id: row.doi for row in rows}


def _fetch_prefix_publishers(conn: Connection) -> dict[str, str]:
    """Préfixe DOI vers la clé de nom de son éditeur."""
    rows = conn.execute(
        text(
            "SELECT d.prefix, p.name FROM doi_prefixes d JOIN publishers p ON p.id = d.publisher_id"
        )
    )
    return {row.prefix: publisher_name_key(row.name) for row in rows}


def _side_columns(side: Side, suffix: str, sources: list[str]) -> dict[str, object]:
    return {
        f"titre_{suffix}": side.journal.title,
        f"type_{suffix}": side.journal.journal_type,
        f"issn_{suffix}": " ".join(sorted(side.journal.issns)),
        f"editeur_{suffix}": side.journal.publisher,
        f"sources_{suffix}": ",".join(sources),
    }


def _audit(
    sides: dict[int, dict[int, Side]],
    dois: dict[int, str],
    prefix_publishers: dict[str, str],
) -> list[dict[str, object]]:
    """Une ligne par couple de revues : sa cause, ses publications, et les deux revues."""
    occurrences = [
        (publication_id, first, second)
        for publication_id, by_journal in sides.items()
        for first, second in combinations(sorted(by_journal), 2)
    ]
    seen: Counter[tuple[int, int]] = Counter((first, second) for _, first, second in occurrences)
    causes: defaultdict[tuple[int, int], Counter[Cause]] = defaultdict(Counter)
    publications: defaultdict[tuple[int, int], list[int]] = defaultdict(list)
    non_conforme: defaultdict[tuple[int, int], Counter[str]] = defaultdict(Counter)
    for publication_id, first, second in occurrences:
        a, b = sides[publication_id][first], sides[publication_id][second]
        doi = dois.get(publication_id, "")
        prefix_publisher = prefix_publishers.get(doi.split("/", 1)[0], "")
        pair = (first, second)
        causes[pair][_cause(a, b, prefix_publisher, seen[pair])] += 1
        publications[pair].append(publication_id)
        side = _wrong_side(a, b, prefix_publisher)
        if side is not None:
            non_conforme[pair][",".join(sorted(side.sources))] += 1

    rows: list[dict[str, object]] = []
    for pair, counted in causes.items():
        first, second = pair
        seen_in = publications[pair]
        example = seen_in[0]
        sources_a = sorted({s for p in seen_in for s in sides[p][first].sources})
        sources_b = sorted({s for p in seen_in for s in sides[p][second].sources})
        wrong = non_conforme[pair].most_common(1)
        rows.append(
            {
                "cause": counted.most_common(1)[0][0],
                "publications": len(seen_in),
                "revue_a": first,
                "revue_b": second,
                "cote_non_conforme": wrong[0][0] if wrong else "",
                "exemple_publication": example,
                "exemple_doi": dois.get(example, ""),
                **_side_columns(sides[example][first], "a", sources_a),
                **_side_columns(sides[example][second], "b", sources_b),
            }
        )
    rows.sort(key=lambda row: (str(row["cause"]), -int(str(row["publications"]))))
    return rows


def _report(rows: list[dict[str, object]], divergent: int, samples: int) -> None:
    log.info("Publications dont les revues divergent : %d", divergent)
    log.info("Couples de revues distincts                : %d", len(rows))
    log.info("─── Par cause ───")
    for cause in Cause:
        of_cause = [row for row in rows if row["cause"] == cause]
        if not of_cause:
            continue
        log.info(
            "%-30s %5d couples, %5d publications",
            cause,
            len(of_cause),
            sum(int(str(row["publications"])) for row in of_cause),
        )
        for row in of_cause[:samples]:
            log.info(
                "    %4s publ. « %s » [%s] ⟂ « %s » [%s] — publication %s",
                row["publications"],
                row["titre_a"],
                row["sources_a"],
                row["titre_b"],
                row["sources_b"],
                row["exemple_publication"],
            )


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    log.info("Détail par couple de revues : %s", path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv-out", default=str(_DEFAULT_CSV), help=f"Chemin du CSV (défaut : {_DEFAULT_CSV})."
    )
    parser.add_argument(
        "--samples", type=int, default=5, help="Exemples affichés par cause (défaut : 5)."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        journals = _fetch_journals(conn)
        sides = _fetch_sides(conn, journals)
        dois = _fetch_dois(conn)
        prefix_publishers = _fetch_prefix_publishers(conn)

    rows = _audit(sides, dois, prefix_publishers)
    _report(rows, len(sides), args.samples)
    _write_csv(rows, Path(args.csv_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
