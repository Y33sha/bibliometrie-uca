"""Phase `metadata_correction` — sous-étape **doi_targets** : cible du DOI des formes secondaires DataCite.

Le DOI d'une forme secondaire a pour cible le DOI de l'œuvre principale présente en base : version → concept (`IsVersionOf`), forme variante / copie repository → version publiée (`IsVariantFormOf`), pièce d'un dataset → dataset parent (`IsPartOf`, ou collection figshare de même titre pour un fichier complémentaire figshare). La cible tient lieu du DOI pour tous les enregistrements sources qui ont ce DOI. La sous-étape matchable écarte de la réconciliation l'enregistrement source DataCite de la forme secondaire.

La table `doi_targets` est réécrite à chaque passage : une relation disparue, ou une cible sortie de la base, retire la cible.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.source_records.metadata_correction.shared_doi import (
    DoiTarget,
    SecondaryFormDeclaration,
    doi_target,
)
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_store import (
    SecondaryFormRow,
    SourceRecordCorrectionStore,
)


def compute_doi_targets(rows: list[SecondaryFormRow]) -> list[DoiTarget]:
    """Cible de chaque DOI déclaré forme secondaire (`doi_target`)."""
    declarations: dict[str, list[SecondaryFormDeclaration]] = defaultdict(list)
    for row in rows:
        declarations[row.doi].append(row.declaration)
    return [
        target
        for doi, declared in declarations.items()
        if (target := doi_target(declared, doi=doi)) is not None
    ]


@dataclass
class DoiTargetStats:
    """Bilan de la sous-étape : déclarations examinées, DOI dont la cible change, et nombre de cibles par règle."""

    examined: int
    changed: int
    rule_counts: dict[str, int]


def run(
    conn: Connection, store: SourceRecordCorrectionStore, logger: logging.Logger
) -> DoiTargetStats:
    """Réécrit `doi_targets`."""
    step(logger, "Cibles des DOI de formes secondaires")
    t0 = time.perf_counter()
    rows = store.fetch_secondary_form_declarations()
    logger.info(
        "%s%s %s", BRANCH, quantity(len(rows), "déclaration"), inflect(len(rows), "examinée")
    )

    targets = compute_doi_targets(rows)
    changed = store.replace_doi_targets(targets)
    logger.info(
        "%s%s, dont %s",
        BRANCH,
        quantity(len(targets), "cible"),
        quantity(changed, "modifiée", "modifiées"),
    )
    rule_counts: dict[str, int] = {}
    for target in targets:
        rule_counts[target.rule.value] = rule_counts.get(target.rule.value, 0) + 1

    logger.info("%sTerminé en %.1fs", LAST_BRANCH, time.perf_counter() - t0)
    return DoiTargetStats(len(rows), changed, rule_counts)
