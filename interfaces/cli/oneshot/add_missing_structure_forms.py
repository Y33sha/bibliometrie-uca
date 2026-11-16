# STATUS: oneshot (2026-11-16)
"""Ajoute les formes de nom et les rattachements HAL manquants relevés par l'audit des désaccords entre sources.

Une adresse ou une structure HAL sans rattachement au périmètre donne une affiliation contraire à une autre source, alors que les deux désignent la même structure. Le script ajoute les formes de nom par le service des structures, comme l'interface d'administration, et rattache les structures HAL de QuaPA à leur structure interne. Une forme ou un rattachement déjà présents restent en place. Les phases suivantes appliquent les ajouts :
    run_pipeline --from affiliations

Usage :
    uv run python -m interfaces.cli.oneshot.add_missing_structure_forms [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import Connection, text

from application.ports.repositories.structure_repository import NameFormCreate
from application.services.structures import StructureService
from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import perimeter_repository, structure_repository
from pipeline.public import PerimeterStructures

log = setup_logger("add_missing_structure_forms", os.path.dirname(__file__))

SITE_CLERMONT, UCA, INRAE = "site_clermont", "uca", "inrae"

FORMS: list[tuple[str, str, bool, tuple[str, ...]]] = [
    # (structure, forme, mot entier, contexte)
    ("chu_clermont", "university teaching hospital", False, (SITE_CLERMONT,)),
    ("chu_clermont", "univ teaching hosp", False, (SITE_CLERMONT,)),
    ("chu_clermont", "chu clermont", False, ()),
    ("chu_clermont", "delegat rech clin innovat", False, (SITE_CLERMONT,)),
    ("ip", "lasmea", True, ()),
    ("iccf", "seesib", True, ()),
    ("unh", "nutr humaine", False, (UCA, SITE_CLERMONT, INRAE)),
    ("quapa", "ur370", True, ()),
    ("quapa", "qual prod anim", False, ()),
    ("medis", "ur454", True, ()),
    ("umrh", "umr herbivores", False, ()),
    ("uca", "univ clermont i", True, ()),
]
"""Formes de nom à ajouter. Le contexte nomme des structures par leur code."""

HAL_LINKS: dict[str, tuple[int, ...]] = {"quapa": (1002065, 37712)}
"""Structures HAL à rattacher, par code de structure interne."""


def structure_ids(conn: Connection) -> dict[str, int]:
    codes = {code for code, *_ in FORMS} | {c for *_, ctx in FORMS for c in ctx} | set(HAL_LINKS)
    rows = conn.execute(
        text("SELECT code, id FROM structures WHERE code = ANY(:codes)"), {"codes": list(codes)}
    )
    ids = {r.code: r.id for r in rows}
    if missing := codes - ids.keys():
        raise SystemExit(f"structures introuvables : {sorted(missing)}")
    return ids


def existing_forms(conn: Connection) -> set[tuple[int, str]]:
    rows = conn.execute(text("SELECT structure_id, form_text FROM structure_name_forms"))
    return {(r.structure_id, r.form_text) for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        ids = structure_ids(conn)
        existing = existing_forms(conn)
        service = StructureService(
            structures=structure_repository(conn),
            perimeters=perimeter_repository(conn),
            perimeter_structures=PerimeterStructures(conn),
        )
        created = 0
        for code, form, word_boundary, context in FORMS:
            if (ids[code], normalize_text(form)) in existing:
                log.info("forme déjà présente : %s « %s »", code, form)
                continue
            log.info("forme à ajouter : %s « %s »", code, form)
            created += 1
            if not args.dry_run:
                service.create_name_form(
                    NameFormCreate(
                        structure_id=ids[code],
                        form_text=form,
                        is_word_boundary=word_boundary,
                        requires_context_of=[ids[c] for c in context] or None,
                    )
                )
        linked = 0
        for code, hal_ids in HAL_LINKS.items():
            statement = text(
                "UPDATE hal_structures SET structure_id = :structure_id"
                " WHERE hal_structure_id = ANY(:hal_ids) AND structure_id IS NULL"
            )
            if args.dry_run:
                continue
            linked += conn.execute(
                statement, {"structure_id": ids[code], "hal_ids": list(hal_ids)}
            ).rowcount
        log.info("%d formes ajoutées, %d structures HAL rattachées", created, linked)
        if args.dry_run:
            conn.rollback()
            return
        log.info("Ensuite : run_pipeline --from affiliations")


if __name__ == "__main__":
    main()
