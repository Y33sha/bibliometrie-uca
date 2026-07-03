# STATUS: oneshot (2026-06-17)
"""Dump (chantier dedup-pairwise) des couples openalex+scanr réunis par métadonnées (sans DOI)
SANS recouvrement d'auteurs sous `names_compatible` — pour qualifier l'excédent à la main
(artefact d'ordre des noms OpenAlex vs vraie sur-fusion book_chapter).

Lance : python -m interfaces.cli.oneshot.audit_dedup_overmerge_examples
"""

from collections import defaultdict

from sqlalchemy import text

from domain.persons.name_matching import names_compatible, parse_raw_author_name
from infrastructure.db.engine import get_sync_engine

SQL = text("""
    WITH g AS (
        SELECT doc_type, title_normalized, pub_year FROM source_publications
        WHERE doi IS NULL AND doc_type IS NOT NULL AND pub_year IS NOT NULL
          AND length(title_normalized) > 30
        GROUP BY doc_type, title_normalized, pub_year HAVING count(*) = 2
    )
    SELECT (sp.title_normalized || ' ['||sp.doc_type||' '||sp.pub_year||']') AS grp,
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


def overlap(a1: list[str], a2: list[str]) -> bool:
    p1 = [parse_raw_author_name(a) for a in a1]
    p2 = [parse_raw_author_name(a) for a in a2]
    return any(names_compatible(l1, f1, l2, f2) for l1, f1 in p1 for l2, f2 in p2)


def main() -> None:
    engine = get_sync_engine()
    with engine.connect() as conn:
        groups = defaultdict(list)
        for row in conn.execute(SQL):
            groups[row.grp].append((row.source, list(row.authors)))

    shown = 0
    for grp, sps in groups.items():
        if len(sps) != 2:
            continue
        (s1, a1), (s2, a2) = sps
        if {s1, s2} != {"openalex", "scanr"} or not a1 or not a2:
            continue
        if overlap(a1, a2):
            continue
        shown += 1
        print(f"\n— {grp[:75]}")
        print(f"   {s1:9}: {', '.join(a1[:6])}")
        print(f"   {s2:9}: {', '.join(a2[:6])}")
        if shown >= 12:
            break


if __name__ == "__main__":
    main()
