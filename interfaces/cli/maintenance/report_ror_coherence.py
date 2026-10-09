# STATUS: maintenance
"""Rapport de cohérence entre `structure_tutelles` et les relations parent/enfant du référentiel ROR.

Liste les tutelles absentes du ROR, les parents ROR absents des tutelles, les parents et enfants ROR des structures du périmètre absents de `structures`, et les ROR attribués à plusieurs structures. Chaque écart se corrige dans l'interface d'administration ou se signale au ROR.

Usage :
    python -m interfaces.cli.maintenance.report_ror_coherence
"""

import sys

from application.services.structures.ror import RorCoherenceReport, ror_coherence_report
from domain.structures.identifiers import RorId
from infrastructure.db.engine import get_sync_engine
from infrastructure.read_models.ror import PgRorCoherenceQueries


def _section(title: str, lines: list[str]) -> None:
    print(f"\n{title} : {len(lines)}")
    for line in sorted(lines):
        print(f"  {line}")


def _print(report: RorCoherenceReport) -> None:
    c, code = report.coherence, report.codes

    def ror(ror_id: RorId) -> str:
        return f"{ror_id} {report.ror_names.get(ror_id, '?')}"

    _section(
        "Tutelles absentes du ROR",
        [f"{code[p]} → {code[e]}" for p, e in c.absent_from_ror],
    )
    _section(
        "Parents ROR absents des tutelles",
        [f"{code[p]} → {code[e]}" for p, e in c.uncovered_ror_parents],
    )
    _section(
        "Parents ROR absents de structures",
        [f"{ror(r)} → {code[e]}" for e, r in c.outside_parents],
    )
    _section(
        "Enfants ROR absents de structures",
        [f"{code[p]} → {ror(r)}" for p, r in c.outside_children],
    )
    _section(
        "ROR attribués à plusieurs structures",
        [
            f"{ror(r)} : {', '.join(sorted(code[s] for s, sr in report.ror_ids.items() if sr == r))}"
            for r in c.shared_ror_ids
        ],
    )


def main() -> int:
    with get_sync_engine().connect() as conn:
        queries = PgRorCoherenceQueries(conn)
        if not queries.ror_relations():
            print(
                "Référentiel ROR vide : lancer python -m interfaces.cli.imports.import_ror_dump",
                file=sys.stderr,
            )
            return 1
        _print(ror_coherence_report(queries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
