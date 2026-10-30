# STATUS: oneshot (2026-10-25)
"""Audit : vote des arbitres sur les domains OpenAlex, confronté à l'échantillon de référence des sujets.

Chaque arbitre se traduit en domains OpenAlex (Health, Life, Physical, Social Sciences) :

- domaines HAL de la publication, par leur code (`_HAL_CODES`, préfixe le plus long) ;
- discipline theses.fr de la publication, par mots-clés (`_THESES_KEYWORDS`) ;
- codes LCC de la revue dans le DOAJ (`_LCC_CODES`, préfixe le plus long) ;
- profil de la revue : domains des autres publications de la revue, d'après leurs domaines HAL et disciplines theses.fr ;
- profil du laboratoire : domains des autres publications du laboratoire, d'après leurs domaines HAL, disciplines theses.fr et revues DOAJ.

Un profil soutient les domains qui pèsent au moins `_PROFILE_SHARE` de ses publications. Il vote seulement s'il réunit au moins `_PROFILE_MIN` publications et ne soutient pas les quatre domains. Une publication rattachée à plusieurs laboratoires additionne leurs soutiens.

Chaque combinaison d'arbitres est mesurée telle quelle, puis avec Health et Life confondus : un soutien à l'un vaut soutien à l'autre.

Règle : sur une publication à plusieurs domains, un domain sans soutien est rejeté si un autre domain a au moins un soutien. Le rejet s'étend aux fields, subfields et topics qui en descendent. Les rejets sont comparés aux verdicts de référence de l'échantillon (`claude.v`), par niveau.

Usage :
    uv run python -m interfaces.cli.oneshot.prototype_subject_vote --sample sample.json
"""

from __future__ import annotations

import argparse
import json
import os
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("prototype_subject_vote", os.path.dirname(__file__))

H, L, P, S = "Health Sciences", "Life Sciences", "Physical Sciences", "Social Sciences"
_LEVELS = ("domain", "field", "subfield", "topic")

_HAL_CODES = {
    "shs": {S},
    "qfin": {S},
    "scco": {S, L, H},
    "sde": {P, L},
    **{code: {P} for code in ("info", "phys", "math", "spi", "chim", "sdu", "stat", "nlin")},
    "sdv": {L},
    "sdv.mhep": {H},
    "sdv.spee": {H},
    "sdv.can": {H},
    "sdv.sp": {H},
    "sdv.ib": {H, P},
    "sdv.neu": {H, L},
    "sdv.imm": {H, L},
    "sdv.mp": {L, H},
    "sdv.aen": {L, H},
    "sdv.tox": {H, L},
    "sdv.gen.gh": {H, L},
}

_LCC_CODES = {
    **{letter: {S} for letter in "BCDEFHJKLMNPZ"},
    "G": {P},
    "GE": {P, L},
    **{code: {S} for code in ("GF", "GN", "GR", "GT", "GV")},
    **{code: {P} for code in ("QA", "QB", "QC", "QD", "QE")},
    **{code: {L} for code in ("QH", "QK", "QL")},
    **{code: {L, H} for code in ("QM", "QP", "QR")},
    "R": {H},
    "S": {L},
    "T": {P},
    "TX": {L, H},
    "U": {P},
    "V": {P},
}

_THESES_KEYWORDS = {
    H: (
        "sante",
        "medecin",
        "pharmac",
        "odontolog",
        "epidemiolog",
        "clinique",
        "neuroscience",
        "staps",
    ),
    L: (
        "biolog",
        "vivant",
        "vie",
        "microbio",
        "ecolog",
        "agricult",
        "agronom",
        "aliment",
        "genetique",
        "physiolog",
        "neuroscience",
        "nutrition",
    ),
    P: (
        "informatique",
        "mathemat",
        "physique",
        "chimie",
        "mecanique",
        "genie",
        "electron",
        "materiau",
        "terre",
        "planete",
        "robotique",
        "image",
        "signal",
        "geolog",
        "automatique",
        "statistique",
        "procede",
        "energ",
        "volcan",
        "astro",
        "optique",
    ),
    S: (
        "econom",
        "gestion",
        "droit",
        "histoire",
        "lettres",
        "langue",
        "linguist",
        "philosoph",
        "sociolog",
        "psycholog",
        "geographie",
        "politique",
        "art",
        "education",
        "information et de la communication",
        "communication",
        "staps",
        "musicolog",
        "anthropolog",
        "litterature",
        "civilisation",
    ),
}

_PROFILE_SHARE = 0.15
_PROFILE_MIN = 20

_EVIDENCE_SQL = """
    SELECT p.id, p.serial_id,
           (SELECT array_agg(DISTINCT split_part(e, '_FacetSep_', 1))
            FROM source_records sr, jsonb_array_elements_text(sr.topics -> 'hal_domains') e
            WHERE sr.publication_id = p.id AND sr.source = 'hal') AS hal_codes,
           (SELECT array_agg(DISTINCT sr.topics ->> 'discipline')
            FROM source_records sr
            WHERE sr.publication_id = p.id AND sr.source = 'theses' AND sr.topics ? 'discipline') AS disciplines,
           (SELECT array_agg(DISTINCT ps.structure_id)
            FROM publication_structures ps JOIN structures st ON st.id = ps.structure_id
            WHERE ps.publication_id = p.id AND st.structure_type = 'labo') AS labs
    FROM publications p
"""

_LCC_SQL = """
    SELECT id, doaj_payload ->> 'LCC Codes' AS lcc FROM serials WHERE doaj_payload ? 'LCC Codes'
"""


def _by_longest_prefix(code: str, table: dict[str, set[str]], separator: str) -> set[str]:
    parts = code.split(separator) if separator else [code[:i] for i in range(len(code), 0, -1)]
    candidates = (
        [separator.join(parts[:n]) for n in range(len(parts), 0, -1)] if separator else parts
    )
    for candidate in candidates:
        if candidate in table:
            return table[candidate]
    return set()


def hal_domains(codes: list[str] | None) -> set[str]:
    return {d for code in codes or [] for d in _by_longest_prefix(code.lower(), _HAL_CODES, ".")}


def lcc_domains(lcc: str | None) -> set[str]:
    letters = [
        "".join(ch for ch in code.strip() if ch.isalpha()) for code in (lcc or "").split("|")
    ]
    return {d for code in letters if code for d in _by_longest_prefix(code, _LCC_CODES, "")}


def theses_domains(disciplines: list[str] | None) -> set[str]:
    found: set[str] = set()
    for discipline in disciplines or []:
        plain = unicodedata.normalize("NFKD", discipline.lower()).encode("ascii", "ignore").decode()
        found |= {
            domain for domain, words in _THESES_KEYWORDS.items() if any(w in plain for w in words)
        }
    return found


def _profile(counts: Counter[str], total: int) -> set[str]:
    if total < _PROFILE_MIN:
        return set()
    supported = {d for d, n in counts.items() if n / total >= _PROFILE_SHARE}
    return set() if len(supported) == 4 else supported


def _descendants(labels: list[dict], rejected_domains: set[str]) -> set[str]:
    by_key = {(label["level"], label["label"]): label for label in labels}
    rejected: set[str] = set()
    for label in labels:
        node = label
        while node is not None:
            if node["level"] == "domain" and node["label"] in rejected_domains:
                rejected.add(label["id"])
                break
            depth = _LEVELS.index(node["level"])
            node = by_key.get((_LEVELS[depth - 1], node["parent"])) if depth else None
    return rejected


def evaluate(name: str, sample: list[dict], support: dict[int, Counter[str]]) -> None:
    by_level: dict[str, Counter[tuple[bool, str]]] = defaultdict(Counter)
    voting = 0
    multi = 0
    for publication in sample:
        labels = publication["labels"]
        domains = {label["label"] for label in labels if label["level"] == "domain"}
        votes = support.get(publication["id"], Counter())
        rejected_domains: set[str] = set()
        if len(domains) > 1:
            multi += 1
            if any(votes[d] for d in domains):
                voting += 1
                rejected_domains = {d for d in domains if not votes[d]}
        rejected = _descendants(labels, rejected_domains)
        for label in labels:
            by_level[label["level"]][(label["id"] in rejected, label["claude"]["v"])] += 1
    log.info("%s : vote sur %d publications à plusieurs domains sur %d", name, voting, multi)
    totals: Counter[tuple[bool, str]] = Counter()
    for level in _LEVELS:
        counts = by_level[level]
        totals.update(counts)
        log.info("  %-8s %s", level, _scores(counts))
    log.info("  %-8s %s", "total", _scores(totals))


def _scores(counts: Counter[tuple[bool, str]]) -> str:
    true_positive, false_positive = counts[(True, "aberrant")], counts[(True, "pertinent")]
    false_negative = counts[(False, "aberrant")]
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
    )
    return (
        f"rejetés {true_positive + false_positive + counts[(True, 'limite')]} : aberrants {true_positive}, "
        f"pertinents {false_positive}, limites {counts[(True, 'limite')]} ; aberrants manqués {false_negative} ; "
        f"précision {precision:.0%}, rappel {recall:.0%}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True, help="Échantillon qualifié (JSON).")
    sample = json.loads(parser.parse_args().sample.read_text(encoding="utf-8"))

    with get_sync_engine().connect() as conn:
        lcc = {row.id: lcc_domains(row.lcc) for row in conn.execute(text(_LCC_SQL))}
        rows = conn.execute(text(_EVIDENCE_SQL)).all()

    own: dict[int, set[str]] = {}
    serial_of: dict[int, int | None] = {}
    labs_of: dict[int, list[int]] = {}
    serial_counts: dict[int, Counter[str]] = defaultdict(Counter)
    serial_totals: Counter[int] = Counter()
    lab_counts: dict[int, Counter[str]] = defaultdict(Counter)
    lab_totals: Counter[int] = Counter()
    publication_evidence: dict[int, set[str]] = {}
    for row in rows:
        evidence = hal_domains(row.hal_codes) | theses_domains(row.disciplines)
        own[row.id] = evidence
        serial_of[row.id] = row.serial_id
        labs_of[row.id] = row.labs or []
        if evidence and row.serial_id is not None:
            serial_counts[row.serial_id].update(evidence)
            serial_totals[row.serial_id] += 1
        with_serial = evidence | lcc.get(row.serial_id, set())
        publication_evidence[row.id] = with_serial
        if with_serial:
            for lab in labs_of[row.id]:
                lab_counts[lab].update(with_serial)
                lab_totals[lab] += 1

    direct: dict[int, Counter[str]] = {}
    serial_profile: dict[int, Counter[str]] = {}
    lab_profile: dict[int, Counter[str]] = {}
    for publication in sample:
        pid = publication["id"]
        direct[pid] = Counter(own[pid] | lcc.get(serial_of[pid], set()))
        serial_id = serial_of[pid]
        serial_profile[pid] = Counter()
        if serial_id is not None:
            counts = serial_counts[serial_id] - Counter(own[pid])
            total = serial_totals[serial_id] - (1 if own[pid] else 0)
            serial_profile[pid] = Counter(_profile(counts, total))
        lab_profile[pid] = Counter()
        for lab in labs_of[pid]:
            counts = lab_counts[lab] - Counter(publication_evidence[pid])
            total = lab_totals[lab] - (1 if publication_evidence[pid] else 0)
            lab_profile[pid].update(_profile(counts, total))

    variants = {
        "arbitres de la publication (HAL, theses.fr, DOAJ)": direct,
        "profil de la revue": serial_profile,
        "profil des laboratoires": lab_profile,
        "arbitres de la publication + laboratoires": {
            p: direct[p] + lab_profile[p] for p in direct
        },
        "arbitres de la publication + revue + laboratoires": {
            p: direct[p] + serial_profile[p] + lab_profile[p] for p in direct
        },
    }
    for name, support in variants.items():
        evaluate(name, sample, support)
    for name, support in variants.items():
        evaluate(
            f"{name}, Health et Life confondus",
            sample,
            {p: _merge_biomedical(c) for p, c in support.items()},
        )
    return 0


def _merge_biomedical(votes: Counter[str]) -> Counter[str]:
    """Confond Health et Life : un soutien à l'un vaut soutien à l'autre."""
    merged = Counter(votes)
    biomedical = votes[H] + votes[L]
    if biomedical:
        merged[H] = merged[L] = biomedical
    return merged


if __name__ == "__main__":
    raise SystemExit(main())
