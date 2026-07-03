# STATUS: oneshot (2026-06-17)
"""Audit (chantier dedup-pairwise) : non-recouvrement d'auteurs sous `names_compatible`.

Compare, par paire de sources, le % de couples de SPs SANS recouvrement d'auteurs (matching
compatible : initiales, accents, ordre nom/prénom) entre :
- couples réunis par DOI (vérité terrain « même œuvre ») = bruit de fond ;
- couples réunis par métadonnées sans DOI (token metadata_block) = à valider.

Si méta ≈ DOI par paire de sources → pas d'excédent de collision (le résidu = artefacts de
matching de noms + vraies collisions). Lance : python -m interfaces.cli.oneshot.audit_dedup_author_overlap
"""

from collections import defaultdict

from sqlalchemy import Connection, TextClause, text

from domain.persons.name_matching import names_compatible, parse_raw_author_name
from infrastructure.db.engine import get_sync_engine

_DOI_SQL = text("""
    WITH g AS (
        SELECT doi FROM source_publications WHERE doi IS NOT NULL
        GROUP BY doi HAVING count(*) = 2
    )
    SELECT sp.doi AS grp, sp.source::text AS source,
           array_remove(array_agg(aik.author_name_normalized), NULL) AS authors
    FROM source_publications sp JOIN g ON g.doi = sp.doi
    LEFT JOIN source_authorships sa
        ON sa.source_publication_id = sp.id
    LEFT JOIN author_identifying_keys aik
        ON aik.id = sa.identity_id AND aik.author_name_normalized <> ''
    GROUP BY sp.doi, sp.id, sp.source
""")

_MD_SQL = text("""
    WITH g AS (
        SELECT doc_type, title_normalized, pub_year FROM source_publications
        WHERE doi IS NULL AND doc_type IS NOT NULL AND pub_year IS NOT NULL
          AND length(title_normalized) > 30
        GROUP BY doc_type, title_normalized, pub_year HAVING count(*) = 2
    )
    SELECT (sp.doc_type || '|' || sp.title_normalized || '|' || sp.pub_year) AS grp,
           sp.source::text AS source,
           array_remove(array_agg(aik.author_name_normalized), NULL) AS authors
    FROM source_publications sp JOIN g USING (doc_type, title_normalized, pub_year)
    LEFT JOIN source_authorships sa
        ON sa.source_publication_id = sp.id
    LEFT JOIN author_identifying_keys aik
        ON aik.id = sa.identity_id AND aik.author_name_normalized <> ''
    WHERE sp.doi IS NULL
    GROUP BY sp.doc_type, sp.title_normalized, sp.pub_year, sp.id, sp.source
""")


def _lists_overlap(a1: list[str], a2: list[str]) -> bool:
    p1 = [parse_raw_author_name(a) for a in a1]
    p2 = [parse_raw_author_name(a) for a in a2]
    return any(names_compatible(ln1, fn1, ln2, fn2) for ln1, fn1 in p1 for ln2, fn2 in p2)


def _analyze(conn: Connection, sql: TextClause) -> dict[str, list[int]]:
    groups: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for row in conn.execute(sql):
        groups[row.grp].append((row.source, list(row.authors)))
    stat: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # source_pair -> [n, n_sans_recouv]
    for sps in groups.values():
        if len(sps) != 2:
            continue
        (s1, a1), (s2, a2) = sps
        if not a1 or not a2:  # besoin d'auteurs des deux côtés
            continue
        pair = "+".join(sorted([s1, s2]))
        stat[pair][0] += 1
        if not _lists_overlap(a1, a2):
            stat[pair][1] += 1
    return stat


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as conn:
        doi = _analyze(conn, _DOI_SQL)
        md = _analyze(conn, _MD_SQL)

    pairs = sorted(set(doi) | set(md), key=lambda p: -md.get(p, [0])[0])
    print(f"{'paire sources':18} | {'n DOI':>6} {'%nr DOI':>8} | {'n méta':>6} {'%nr méta':>9}")
    print("-" * 60)
    for p in pairs:
        nd, ndnr = doi.get(p, [0, 0])
        nm, nmnr = md.get(p, [0, 0])
        if nm < 30:
            continue
        dpct = f"{100 * ndnr / nd:.2f}" if nd else "—"
        mpct = f"{100 * nmnr / nm:.2f}" if nm else "—"
        print(f"{p:18} | {nd:6d} {dpct:>8} | {nm:6d} {mpct:>9}")


if __name__ == "__main__":
    main()
