# STATUS: oneshot (2026-10-25)
"""Audit (lecture seule) : échantillon de référence pour évaluer la pertinence des sujets OpenAlex.

Tire des publications sans remise : d'abord `--random` publications au hasard, puis par strate, dans cet ordre :

1. revues généralistes : revues d'au moins 20 publications, réparties sur au moins 3 domains OpenAlex, sans domain au-dessus de 60 % ;
2. sans arbitre : publications sans domaine HAL ni discipline theses.fr ;
3. paire rare : plusieurs domains, autre que la seule paire Health × Life ;
4. Health × Life : exactement ces deux domains ;
5. un seul domain.

Le domain d'une publication, pour la répartition d'une revue, est celui de son premier topic OpenAlex. `--scale` multiplie l'effectif de chaque strate. `--exclude` écarte les publications d'un échantillon déjà tiré.

Écrit un fichier JSON : une entrée par publication, avec titre, résumé, revue et l'arbre des libellés OpenAlex (domain, field, subfield, topic), chaque libellé avec un identifiant, son parent et le score maximal des topics qui le portent. Les sujets des autres sources sont exclus : la qualification se fait sur le titre, le résumé et la revue.

Usage :
    uv run python -m interfaces.cli.oneshot.sample_subject_relevance --output sample.json
    uv run python -m interfaces.cli.oneshot.sample_subject_relevance --output annotation.json         --random 175 --scale 1.75 --exclude sample.json --seed 20261027
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("sample_subject_relevance", os.path.dirname(__file__))

_LEVELS = ("domain", "field", "subfield", "topic")
_HEALTH_LIFE = frozenset({"Health Sciences", "Life Sciences"})
_STRATA = (
    ("generalist_serial", 20),
    ("no_arbiter", 20),
    ("rare_pair", 25),
    ("health_life", 15),
    ("single_domain", 20),
)

_CANDIDATES_SQL = """
    SELECT sr.publication_id, p.serial_id, sr.topics,
           EXISTS (
               SELECT 1 FROM source_records a
               WHERE a.publication_id = sr.publication_id
                 AND a.source IN ('hal', 'theses') AND a.topics IS NOT NULL
           ) AS has_arbiter
    FROM source_records sr
    JOIN publications p ON p.id = sr.publication_id
    WHERE sr.source = 'openalex' AND jsonb_typeof(sr.topics) = 'array'
    ORDER BY sr.publication_id, sr.id
"""

_DETAILS_SQL = """
    SELECT p.id, p.title, p.publication_year, p.doi, s.title AS serial,
           (SELECT a.abstract FROM source_records a
            WHERE a.publication_id = p.id AND length(a.abstract) > 100
            ORDER BY (a.source = 'openalex') DESC, length(a.abstract) DESC
            LIMIT 1) AS abstract
    FROM publications p
    LEFT JOIN serials s ON s.id = p.serial_id
    WHERE p.id = ANY(:ids)
"""


def _label_tree(topic_lists: list[list[dict]]) -> list[dict]:
    """Libellés distincts par niveau, avec leur parent et le score maximal des topics qui en descendent."""
    nodes: dict[tuple[str, str], dict] = {}
    for topics in topic_lists:
        for entry in topics:
            score = entry.get("score")
            parent = None
            for level in _LEVELS:
                label = entry.get(level)
                if not isinstance(label, str) or not label.strip():
                    break
                key = (level, label)
                node = nodes.setdefault(
                    key, {"level": level, "label": label, "parent": parent, "score": None}
                )
                if isinstance(score, int | float):
                    node["score"] = max(node["score"] or 0.0, float(score))
                parent = label
    return list(nodes.values())


def _first_domains(topic_lists: list[list[dict]]) -> list[str]:
    return [t[0]["domain"] for t in topic_lists if t and isinstance(t[0].get("domain"), str)]


def sample(output: Path, seed: int, random_size: int, scale: float, excluded: set[int]) -> int:
    with get_sync_engine().connect() as conn:
        topics_by_publication: dict[int, list[list[dict]]] = defaultdict(list)
        serial_by_publication: dict[int, int | None] = {}
        arbiter: dict[int, bool] = {}
        for row in conn.execute(text(_CANDIDATES_SQL)):
            topics_by_publication[row.publication_id].append(row.topics)
            serial_by_publication[row.publication_id] = row.serial_id
            arbiter[row.publication_id] = row.has_arbiter

        domains_by_serial: dict[int, Counter[str]] = defaultdict(Counter)
        for publication_id, topic_lists in topics_by_publication.items():
            serial_id = serial_by_publication[publication_id]
            first = _first_domains(topic_lists)
            if serial_id is not None and first:
                domains_by_serial[serial_id][first[0]] += 1
        generalist_serials = {
            serial_id
            for serial_id, counts in domains_by_serial.items()
            if (total := sum(counts.values())) >= 20
            and len(counts) >= 3
            and max(counts.values()) / total < 0.6
        }

        def domains(publication_id: int) -> frozenset[str]:
            return frozenset(
                e["domain"]
                for topics in topics_by_publication[publication_id]
                for e in topics
                if isinstance(e.get("domain"), str)
            )

        predicates = {
            "generalist_serial": lambda pid: serial_by_publication[pid] in generalist_serials,
            "no_arbiter": lambda pid: not arbiter[pid],
            "rare_pair": lambda pid: len(domains(pid)) >= 2 and domains(pid) != _HEALTH_LIFE,
            "health_life": lambda pid: domains(pid) == _HEALTH_LIFE,
            "single_domain": lambda pid: len(domains(pid)) == 1,
        }

        rng = random.Random(seed)  # noqa: S311 — tirage reproductible, sans usage cryptographique
        pool = sorted(set(topics_by_publication) - excluded)
        drawn: dict[int, str] = {}
        for pid in rng.sample(pool, min(random_size, len(pool))):
            drawn[pid] = "random"
        log.info("random : %d tirées sur %d candidates", min(random_size, len(pool)), len(pool))
        for stratum, size in _STRATA:
            candidates = [pid for pid in pool if pid not in drawn and predicates[stratum](pid)]
            chosen = rng.sample(candidates, min(round(size * scale), len(candidates)))
            for pid in chosen:
                drawn[pid] = stratum
            log.info("%s : %d tirées sur %d candidates", stratum, len(chosen), len(candidates))

        details = {row.id: row for row in conn.execute(text(_DETAILS_SQL), {"ids": list(drawn)})}

    publications = []
    for pid, stratum in drawn.items():
        row = details[pid]
        publications.append(
            {
                "id": pid,
                "stratum": stratum,
                "title": row.title,
                "year": row.publication_year,
                "doi": row.doi,
                "serial": row.serial,
                "abstract": row.abstract,
                "labels": [
                    {"id": f"{pid}-{n}", **node}
                    for n, node in enumerate(_label_tree(topics_by_publication[pid]))
                ],
            }
        )
    output.write_text(json.dumps(publications, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info(
        "%d publications, %d libellés écrits dans %s",
        len(publications),
        sum(len(p["labels"]) for p in publications),
        output,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Fichier JSON écrit.")
    parser.add_argument("--seed", type=int, default=20261025, help="Graine du tirage.")
    parser.add_argument("--random", type=int, default=0, help="Publications tirées au hasard.")
    parser.add_argument("--scale", type=float, default=1.0, help="Facteur appliqué aux strates.")
    parser.add_argument(
        "--exclude", type=Path, help="Échantillon (JSON) dont les publications sont écartées."
    )
    args = parser.parse_args()
    excluded = (
        {p["id"] for p in json.loads(args.exclude.read_text(encoding="utf-8"))}
        if args.exclude
        else set()
    )
    return sample(args.output, args.seed, args.random, args.scale, excluded)


if __name__ == "__main__":
    raise SystemExit(main())
