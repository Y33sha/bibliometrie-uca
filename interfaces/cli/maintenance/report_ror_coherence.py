# STATUS: maintenance
"""Rapport de cohérence entre `structure_parents` et les relations parent/enfant du référentiel ROR.

Liste les tutelles absentes du ROR, les parents ROR absents des tutelles, les parents et enfants ROR des structures du périmètre absents de `structures`, et les ROR attribués à plusieurs structures. Chaque écart se corrige dans l'interface d'administration ou se signale au ROR.

Usage :
    uv run python -m interfaces.cli.maintenance.report_ror_coherence
"""

import sys
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.structures.identifiers import RorId
from domain.structures.ror_coherence import TutelleCoherence, tutelle_coherence
from infrastructure.db.engine import get_sync_engine


@dataclass(frozen=True, slots=True)
class RorCoherenceReport:
    """Écarts entre les référentiels, avec le code de chaque structure et le nom de chaque organisation ROR citée."""

    coherence: TutelleCoherence
    codes: dict[int, str]
    ror_ids: dict[int, RorId]
    ror_names: dict[RorId, str]


def ror_relations(conn: Connection) -> list[tuple[RorId, RorId]]:
    """Renvoie les couples `(parent, enfant)` de `ror_relations`."""
    rows = conn.execute(text("SELECT parent_ror_id, child_ror_id FROM ror_relations"))
    return [(RorId(r.parent_ror_id), RorId(r.child_ror_id)) for r in rows]


def ror_names(conn: Connection, ror_ids: Iterable[RorId]) -> dict[RorId, str]:
    rows = conn.execute(
        text("SELECT ror_id, name FROM ror_organizations WHERE ror_id = ANY(:ids)"),
        {"ids": [r.value for r in ror_ids]},
    )
    return {RorId(r.ror_id): r.name for r in rows}


def ror_coherence_report(conn: Connection) -> RorCoherenceReport:
    """Compare `structure_parents` aux relations du ROR, pour toutes les structures pourvues d'un ROR."""
    structures = conn.execute(text("SELECT id, code, ror_id FROM structures ORDER BY code")).all()
    structure_rors = {
        s.id: ror_id for s in structures if (ror_id := RorId.try_parse(s.ror_id)) is not None
    }
    tutelles = conn.execute(text("SELECT parent_id, child_id FROM structure_parents"))
    perimeter = conn.execute(text("SELECT DISTINCT structure_id FROM perimeter_structures"))
    coherence = tutelle_coherence(
        structure_rors=structure_rors,
        tutelles=[(r.parent_id, r.child_id) for r in tutelles],
        ror_edges=ror_relations(conn),
        scope=frozenset(perimeter.scalars()),
    )
    cited = {r for _, r in coherence.outside_parents | coherence.outside_children}
    return RorCoherenceReport(
        coherence=coherence,
        codes={s.id: s.code for s in structures},
        ror_ids=structure_rors,
        ror_names=ror_names(conn, cited | coherence.shared_ror_ids),
    )


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
        if not ror_relations(conn):
            print(
                "Référentiel ROR vide : lancer uv run python -m interfaces.cli.imports.import_ror_dump",
                file=sys.stderr,
            )
            return 1
        _print(ror_coherence_report(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
