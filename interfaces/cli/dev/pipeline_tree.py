# STATUS: recurring (dev)
"""Affiche l'arborescence du pipeline : phases, étapes et tâches, avec la phrase d'entrées → sorties de chaque étape.

Usage :
    uv run python -m interfaces.cli.dev.pipeline_tree [PHASE] [--interface]

`--interface` ajoute sous chaque étape les tables lues hors de l'étape et les tables écrites par l'étape, d'après les déclarations des tâches. Les files d'attente et la configuration sont omises.
"""

import argparse

from pipeline.graph import Step, Task, interface
from pipeline.phases import PHASES

_INDENT = "    "


def _tables(items: frozenset[str]) -> str:
    """Renvoie les tables de `items`, hors files d'attente et configuration, triées."""
    tables = {item.partition(".")[0] for item in items}
    return ", ".join(sorted(t for t in tables if t != "config" and not t.endswith("_queue")))


def _lines(node: Step | Task, depth: int, with_interface: bool) -> list[str]:
    pad = _INDENT * depth
    if isinstance(node, Task):
        return [f"{pad}· {node.name}"]
    lines = [f"{pad}▸ {node.name} : {node.summary}"]
    if with_interface:
        reads, writes = interface(node.children)
        lines += [
            f"{pad}{_INDENT}lit   : {_tables(reads)}",
            f"{pad}{_INDENT}écrit : {_tables(writes)}",
        ]
    return lines + [
        line for child in node.children for line in _lines(child, depth + 1, with_interface)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Arborescence du pipeline")
    parser.add_argument("phase", nargs="?", choices=[phase.name for phase in PHASES])
    parser.add_argument("--interface", action="store_true", help="Tables lues et écrites par étape")
    args = parser.parse_args()
    for phase in PHASES:
        if args.phase in (None, phase.name):
            print(f"{phase.name} : {phase.label}")
            for child in phase.children:
                print("\n".join(_lines(child, 1, args.interface)))


if __name__ == "__main__":
    main()
