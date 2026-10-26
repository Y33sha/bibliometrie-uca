# STATUS: oneshot (2026-10-25)
"""Audit : classifieurs ISTEX halClass et openAlexClass confrontés à l'échantillon de référence des sujets.

Lit l'échantillon qualifié (sortie de `sample_subject_relevance`, chaque libellé portant son verdict de référence sous `claude.v`). Envoie le titre et le résumé de chaque publication aux deux services, par lots. openAlexClass reçoit seulement les textes anglais. halClass reçoit chaque texte sur son point d'entrée français ou anglais. Les réponses sont écrites dans un fichier JSON, relu tel quel par un passage suivant avec `--reuse`.

Mesure, pour chaque classifieur :

- l'exactitude : part des publications dont le domain proposé figure parmi les domains de référence pertinents ;
- la règle de rejet « un domain OpenAlex absent de la proposition est rejeté » : précision et rappel face aux domains de référence aberrants, sur toutes les publications puis sur celles à plusieurs domains ;
- pour openAlexClass, la même règle au grain field.

Un domaine HAL de premier niveau couvre un ou plusieurs domains OpenAlex (`_HAL_TO_OPENALEX`).

Usage :
    python -m interfaces.cli.oneshot.evaluate_istex_classifiers --sample sample.json --output istex.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

import httpx2

from infrastructure.observability.log import setup_logger

log = setup_logger("evaluate_istex_classifiers", os.path.dirname(__file__))

_OPENALEX_URL = "https://openalex-classification.services.istex.fr/v1/classif"
_HAL_URLS = {
    "en": "https://hal-classifier.services.istex.fr/v1/en/classhalen",
    "fr": "https://hal-classifier.services.istex.fr/v1/fr/classhalfr",
}
_BATCH = 20

_HEALTH, _LIFE, _PHYSICAL, _SOCIAL = (
    "Health Sciences",
    "Life Sciences",
    "Physical Sciences",
    "Social Sciences",
)
_HAL_TO_OPENALEX = {
    "shs": {_SOCIAL},
    "sdv": {_LIFE, _HEALTH},
    "scco": {_SOCIAL, _LIFE, _HEALTH},
    "sde": {_PHYSICAL, _LIFE},
    "qfin": {_SOCIAL},
    **{
        code: {_PHYSICAL} for code in ("sdu", "spi", "info", "phys", "chim", "math", "stat", "nlin")
    },
}

_FRENCH_WORDS = re.compile(r"\b(les|des|est|une|dans|pour|sur|par|qui|avec|cette|sont)\b")
_ENGLISH_WORDS = re.compile(r"\b(the|and|of|is|are|with|this|that|for|which|from|we)\b")


def _language(text: str) -> str:
    lowered = text.lower()
    return (
        "fr" if len(_FRENCH_WORDS.findall(lowered)) > len(_ENGLISH_WORDS.findall(lowered)) else "en"
    )


def _canonical(label: str) -> str:
    """Forme comparable d'un libellé OpenAlex : `Biochemistry, Genetics and Molecular Biology` et `biochemistry genetics and molecular biology` se rejoignent."""
    return " ".join(re.sub(r"[^a-z ]", " ", label.lower()).split())


def _classify(url: str, items: list[dict[str, str]]) -> dict[str, object]:
    results: dict[str, object] = {}
    for start in range(0, len(items), _BATCH):
        batch = items[start : start + _BATCH]
        response = httpx2.post(url, json=batch, timeout=120)
        response.raise_for_status()
        for entry in response.json():
            results[str(entry["id"])] = entry.get("value")
        log.info(
            "%s : %d / %d", url.rsplit("/", 1)[-1], min(start + _BATCH, len(items)), len(items)
        )
    return results


def call_services(sample: list[dict]) -> dict[str, dict]:
    texts = {str(p["id"]): f"{p['title']}. {p['abstract']}" for p in sample if p.get("abstract")}
    languages = {pid: _language(text) for pid, text in texts.items()}
    openalex = _classify(
        _OPENALEX_URL,
        [
            {"id": pid, "value": text.lower()}
            for pid, text in texts.items()
            if languages[pid] == "en"
        ],
    )
    hal: dict[str, object] = {}
    for language, url in _HAL_URLS.items():
        hal |= _classify(
            url,
            [
                {"id": pid, "value": text}
                for pid, text in texts.items()
                if languages[pid] == language
            ],
        )
    return {
        pid: {"language": languages[pid], "openalex": openalex.get(pid), "hal": hal.get(pid)}
        for pid in texts
    }


def _rule_scores(decisions: list[tuple[bool, str]]) -> str:
    """`decisions` : (rejeté par la règle, verdict de référence). Les libellés limites sont décomptés à part."""
    counts = Counter((rejected, verdict) for rejected, verdict in decisions)
    true_positive = counts[(True, "aberrant")]
    false_positive = counts[(True, "pertinent")]
    false_negative = counts[(False, "aberrant")]
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
    )
    return (
        f"rejetés {sum(n for (r, _), n in counts.items() if r)} dont aberrants {true_positive}, "
        f"pertinents {false_positive}, limites {counts[(True, 'limite')]} ; "
        f"aberrants manqués {false_negative} ; précision {precision:.0%}, rappel {recall:.0%}"
    )


def report(sample: list[dict], results: dict[str, dict]) -> None:
    by_id = {str(p["id"]): p for p in sample}
    log.info(
        "%d publications avec résumé sur %d, dont %d en anglais",
        len(results),
        len(sample),
        sum(1 for r in results.values() if r["language"] == "en"),
    )
    for name in ("openalex", "hal"):
        exact = evaluated = 0
        all_domains: list[tuple[bool, str]] = []
        multi_domains: list[tuple[bool, str]] = []
        fields: list[tuple[bool, str]] = []
        for pid, result in results.items():
            proposal = result[name]
            if not isinstance(proposal, dict):
                continue
            labels = by_id[pid]["labels"]
            proposed_field: str | None = None
            if name == "openalex":
                proposed_domains = {_canonical(str(proposal.get("domain", "")))}
                proposed_field = _canonical(str(proposal.get("field", "")))
            else:
                proposed_domains = {
                    _canonical(d) for d in _HAL_TO_OPENALEX.get(str(proposal.get("code")), set())
                }
            domains = [label for label in labels if label["level"] == "domain"]
            evaluated += 1
            if any(
                _canonical(d["label"]) in proposed_domains and d["claude"]["v"] == "pertinent"
                for d in domains
            ):
                exact += 1
            for d in domains:
                decision = (_canonical(d["label"]) not in proposed_domains, d["claude"]["v"])
                all_domains.append(decision)
                if len(domains) > 1:
                    multi_domains.append(decision)
            if proposed_field is not None:
                fields.extend(
                    (_canonical(f["label"]) != proposed_field, f["claude"]["v"])
                    for f in labels
                    if f["level"] == "field"
                )
        if not evaluated:
            log.info("%s : aucune réponse", name)
            continue
        log.info(
            "%s : %d publications, domain proposé pertinent pour %d (%.0f %%)",
            name,
            evaluated,
            exact,
            100 * exact / evaluated,
        )
        log.info("%s, domains, toutes publications : %s", name, _rule_scores(all_domains))
        log.info(
            "%s, domains, publications à plusieurs domains : %s", name, _rule_scores(multi_domains)
        )
        if fields:
            log.info("%s, fields : %s", name, _rule_scores(fields))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True, help="Échantillon qualifié (JSON).")
    parser.add_argument("--output", type=Path, required=True, help="Réponses des services (JSON).")
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Relit les réponses de --output au lieu d'appeler les services.",
    )
    args = parser.parse_args()
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    if args.reuse:
        results = json.loads(args.output.read_text(encoding="utf-8"))
    else:
        results = call_services(sample)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    report(sample, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
