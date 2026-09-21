# STATUS: oneshot (2026-09-21)
"""Audit (lecture seule) : classement des entrées de `journals` en séries et volumes.

Chaque entrée reçoit une classe :

- **plateforme** : dépôt, serveur de preprints, plateforme d'ebooks ou média, d'après son `journal_type` ;
- **vide** : aucun enregistrement ;
- **revue** : la majorité de ses enregistrements ne sont ni des livres, ni des chapitres, ni des articles de congrès ;
- **série** : ses enregistrements sont surtout des livres, des chapitres ou des articles de congrès, et son titre est celui d'une série (`container_level`) ;
- **volume** : mêmes enregistrements, titre de volume.

Le rapport croise chaque classe avec la présence d'un ISSN, en donne des échantillons, puis regroupe les volumes par clé de série (`series_key`) et éditeur.

Usage :
    python -m interfaces.cli.oneshot.audit_container_levels [--samples 12]
"""

from __future__ import annotations

import argparse
import os
import random
from collections import Counter, defaultdict

from sqlalchemy import text

from domain.journals.series import ContainerLevel, container_level, series_key
from domain.source_publications.doc_types import map_doc_type
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_container_levels", os.path.dirname(__file__))

_PLATFORM_TYPES = frozenset({"repository", "preprint_server", "ebook_platform", "media"})
_MONOGRAPH_DOC_TYPES = frozenset({"book", "book_chapter", "conference_paper"})

_JOURNALS = text("""
    SELECT j.id, j.title, j.journal_type::text AS journal_type, j.publisher_id, j.pub_count,
           (j.issn IS NOT NULL OR j.eissn IS NOT NULL OR j.issnl IS NOT NULL) AS has_issn,
           array_remove(array_agg(s.source::text), NULL) AS sources,
           array_remove(array_agg(coalesce(s.raw_metadata->'doc_type'->>'raw', s.doc_type)), NULL)
               AS raw_types
    FROM journals j
    LEFT JOIN source_publications s ON s.journal_id = j.id
    GROUP BY j.id
""")


def _classify(row) -> str:
    if row.journal_type in _PLATFORM_TYPES:
        return "plateforme"
    if not row.sources:
        return "vide"
    monograph_like = sum(
        bool({map_doc_type(part, source) for part in (raw or "").split(";")} & _MONOGRAPH_DOC_TYPES)
        for source, raw in zip(row.sources, row.raw_types, strict=False)
    )
    if monograph_like * 2 <= len(row.sources):
        return "revue"
    return "volume" if container_level(row.title) is ContainerLevel.VOLUME else "série"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    random.seed(0)

    with get_sync_engine().connect() as conn:
        rows = conn.execute(_JOURNALS).all()

    cells: dict[tuple[str, bool], list] = defaultdict(list)
    for row in rows:
        cells[(_classify(row), row.has_issn)].append(row)

    log.info("%d entrées de journals", len(rows))
    for (classe, has_issn), members in sorted(cells.items()):
        publications = sum(r.pub_count or 0 for r in members)
        log.info(
            "── %s, %s : %d entrées, %d publications",
            classe,
            "avec ISSN" if has_issn else "sans ISSN",
            len(members),
            publications,
        )
        for r in random.sample(members, min(args.samples, len(members))):
            log.info("   %6d  [%s] %s (%d publ.)", r.id, r.journal_type, r.title, r.pub_count or 0)

    series: dict[tuple[str, int | None], list] = defaultdict(list)
    for (classe, _), members in cells.items():
        if classe == "volume":
            for r in members:
                series[(series_key(r.title), r.publisher_id)].append(r)
    groups = {key: members for key, members in series.items() if len(members) > 1}
    log.info(
        "── séries reconnues entre plusieurs volumes : %d, pour %d volumes",
        len(groups),
        sum(len(m) for m in groups.values()),
    )
    sizes = Counter(len(m) for m in groups.values())
    log.info("   tailles : %s", dict(sorted(sizes.items())))
    for (key, _), members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[: args.samples * 2]:
        log.info("   « %s » : %s", key, " | ".join(r.title for r in members[:4]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
