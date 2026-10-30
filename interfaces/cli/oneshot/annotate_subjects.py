# STATUS: oneshot (2026-10-27)
"""Annotation des sujets OpenAlex par un modèle de langage : découpage en lots, fusion des verdicts, comparaison de deux annotations.

Des agents Claude Code annotent les lots, un agent par lot, avec le prompt `subject_annotation_prompt.md`.

- `split` écrit les lots depuis un échantillon (sortie de `sample_subject_relevance`). Les lots omettent la strate et le score OpenAlex.
- `merge` réunit les verdicts des lots et applique la règle d'inclusion : « aberrant » descend aux descendants, puis « pertinent » remonte aux ancêtres. Chaque libellé reçoit un champ `annotation`.
- `compare` mesure l'accord par niveau entre deux échantillons annotés, sur les libellés communs.

Usage :
    uv run python -m interfaces.cli.oneshot.annotate_subjects split --sample annotation.json --out lots/ --size 20
    uv run python -m interfaces.cli.oneshot.annotate_subjects merge --sample annotation.json --verdicts lots/ --output annotated.json
    uv run python -m interfaces.cli.oneshot.annotate_subjects compare --reference reference.json --field claude --candidate annotated.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_LEVELS = ("domain", "field", "subfield", "topic")


def split(sample_path: Path, out: Path, size: int, only: set[int] | None) -> None:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if only is not None:
        sample = [p for p in sample if p["id"] in only]
    out.mkdir(parents=True, exist_ok=True)
    for n, start in enumerate(range(0, len(sample), size)):
        batch = [
            {
                "id": p["id"],
                "title": p["title"],
                "abstract": p["abstract"],
                "serial": p["serial"],
                "year": p["year"],
                "labels": [
                    {k: label[k] for k in ("id", "level", "label", "parent")}
                    for label in p["labels"]
                ],
            }
            for p in sample[start : start + size]
        ]
        (out / f"lot{n:02d}.json").write_text(
            json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    print(f"{len(sample)} publications en {n + 1} lots dans {out}")


def make_consistent(labels: list[dict], field: str) -> int:
    """Applique la règle d'inclusion aux verdicts `label[field]` d'une publication. Renvoie le nombre de verdicts changés."""
    by_key = {(label["level"], label["label"]): label for label in labels}

    def ancestors(label: dict) -> list[dict]:
        chain = []
        node = label
        while (depth := _LEVELS.index(node["level"])) and node["parent"] is not None:
            node = by_key.get((_LEVELS[depth - 1], node["parent"]))
            if node is None:
                break
            chain.append(node)
        return chain

    changed = 0
    for label in labels:
        if label[field]["v"] != "aberrant" and any(
            a[field]["v"] == "aberrant" for a in ancestors(label)
        ):
            label[field] = {"v": "aberrant", "r": "Inclus dans un niveau supérieur aberrant"}
            changed += 1
    for label in labels:
        if label[field]["v"] == "pertinent":
            for ancestor in ancestors(label):
                if ancestor[field]["v"] != "pertinent":
                    ancestor[field] = {
                        "v": "pertinent",
                        "r": "Contient un niveau inférieur pertinent",
                    }
                    changed += 1
    return changed


def merge(sample_path: Path, verdicts_dir: Path, output: Path) -> None:
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    verdicts: dict[str, dict] = {}
    for path in sorted(verdicts_dir.glob("lot*_verdicts.json")):
        verdicts.update(json.loads(path.read_text(encoding="utf-8")))
    annotated, missing, changed = [], 0, 0
    for publication in sample:
        labels = [label for label in publication["labels"] if label["id"] in verdicts]
        if len(labels) < len(publication["labels"]):
            missing += len(publication["labels"]) - len(labels)
            continue
        for label in labels:
            verdict = verdicts[label["id"]]
            label["annotation"] = {"v": verdict["v"], "r": verdict.get("r", "")}
        changed += make_consistent(labels, "annotation")
        annotated.append(publication)
    output.write_text(json.dumps(annotated, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = Counter(label["annotation"]["v"] for p in annotated for label in p["labels"])
    print(
        f"{len(annotated)} publications annotées ; {missing} libellés sans verdict, publications écartées ; "
        f"{changed} verdicts rendus cohérents ; {dict(counts)}"
    )


def compare(reference_path: Path, reference_field: str, candidate_path: Path) -> None:
    reference = {
        label["id"]: (label["level"], label[reference_field]["v"])
        for p in json.loads(reference_path.read_text(encoding="utf-8"))
        for label in p["labels"]
        if reference_field in label
    }
    pairs = [
        (reference[label["id"]][0], reference[label["id"]][1], label["annotation"]["v"])
        for p in json.loads(candidate_path.read_text(encoding="utf-8"))
        for label in p["labels"]
        if label["id"] in reference and "annotation" in label
    ]
    print(f"{len(pairs)} libellés communs")
    for level in (*_LEVELS, None):
        subset = [(r, c) for lv, r, c in pairs if level is None or lv == level]
        if not subset:
            continue
        agree = sum(r == c for r, c in subset)
        strict = [(r, c) for r, c in subset if "limite" not in (r, c)]
        print(
            f"  {level or 'total':9} accord {agree}/{len(subset)} ({agree / len(subset):.0%}) ; "
            f"hors limites {sum(r == c for r, c in strict)}/{len(strict)} ; "
            f"pertinent contre aberrant : {sum({r, c} == {'pertinent', 'aberrant'} for r, c in subset)}"
        )
    print(
        "  confusion (référence → candidat) :",
        dict(Counter((r, c) for _, r, c in pairs if r != c)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_split = sub.add_parser("split")
    p_split.add_argument("--sample", type=Path, required=True)
    p_split.add_argument("--out", type=Path, required=True)
    p_split.add_argument("--size", type=int, default=20)
    p_split.add_argument(
        "--only", type=Path, help="Liste JSON des identifiants de publications gardés."
    )
    p_merge = sub.add_parser("merge")
    p_merge.add_argument("--sample", type=Path, required=True)
    p_merge.add_argument("--verdicts", type=Path, required=True)
    p_merge.add_argument("--output", type=Path, required=True)
    p_compare = sub.add_parser("compare")
    p_compare.add_argument("--reference", type=Path, required=True)
    p_compare.add_argument("--field", default="claude", help="Champ des verdicts de référence.")
    p_compare.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "split":
        only = set(json.loads(args.only.read_text(encoding="utf-8"))) if args.only else None
        split(args.sample, args.out, args.size, only)
    elif args.command == "merge":
        merge(args.sample, args.verdicts, args.output)
    else:
        compare(args.reference, args.field, args.candidate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
