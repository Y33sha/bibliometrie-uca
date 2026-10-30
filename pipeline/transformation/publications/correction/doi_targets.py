"""Sous-étape `doi_targets` de la phase `metadata_correction` : cible du DOI des formes secondaires.

Le DOI d'une forme secondaire DataCite a pour cible le DOI de l'œuvre principale présente en base :

- version → concept (`IsVersionOf`) ;
- forme variante ou copie d'entrepôt → version publiée (`IsVariantFormOf`) ;
- pièce d'un dataset → dataset parent (`IsPartOf`, ou collection figshare de même titre pour un fichier complémentaire figshare).

Un DOI à suffixe de version sans cible déclarée a pour cible sa forme sans version, si c'est le DOI `primary` ou `derived` d'un enregistrement source. Sinon, sa cible est sa version la plus récente en base. La cible tient lieu du DOI pour tous les enregistrements sources ayant ce DOI. La sous-étape `matchable` écarte de la réconciliation l'enregistrement source DataCite de la forme secondaire.

La table `doi_targets` est réécrite à chaque passage : une relation disparue, ou une cible sortie de la base, retire la cible.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Set
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.publications.identifiers import doi_version
from domain.source_records.metadata_correction.shared_doi import (
    DoiTarget,
    SecondaryFormDeclaration,
    doi_target,
    version_targets,
)
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, inflect, quantity, step
from pipeline.transformation.publications.correction.correction_store import (
    SecondaryFormRow,
    SourceRecordCorrectionStore,
)


def compute_doi_targets(
    rows: list[SecondaryFormRow],
    versioned_dois: Iterable[str] = (),
    anchor_dois: Set[str] = frozenset(),
) -> list[DoiTarget]:
    """Calcule la cible de chaque DOI déclaré forme secondaire (`doi_target`), puis de chaque DOI à suffixe de version sans cible déclarée (`version_targets`).

    Args:
        anchor_dois: DOI actifs `primary` ou `derived` des enregistrements sources, parmi les formes sans version.
    """
    declarations: dict[str, list[SecondaryFormDeclaration]] = defaultdict(list)
    for row in rows:
        declarations[row.doi].append(row.declaration)
    declared = [
        target
        for doi, declared in declarations.items()
        if (target := doi_target(declared, doi=doi)) is not None
    ]
    declared_dois = {t.doi for t in declared}
    return declared + [
        t for t in version_targets(versioned_dois, anchor_dois) if t.doi not in declared_dois
    ]


@dataclass
class DoiTargetStats:
    """Bilan de la sous-étape."""

    examined: int
    """Déclarations et DOI à suffixe de version examinés."""
    changed: int
    """DOI à cible changée."""
    rule_counts: dict[str, int]
    """Cibles par règle."""


def run(
    conn: Connection, store: SourceRecordCorrectionStore, logger: logging.Logger
) -> DoiTargetStats:
    """Réécrit `doi_targets`."""
    step(logger, "Cibles des DOI de formes secondaires")
    t0 = time.perf_counter()
    rows = store.fetch_secondary_form_declarations()
    versioned = store.fetch_versioned_dois()
    logger.info(
        "%s%s %s, %s",
        BRANCH,
        quantity(len(rows), "déclaration"),
        inflect(len(rows), "examinée"),
        quantity(len(versioned), "DOI à suffixe de version", "DOI à suffixe de version"),
    )

    unversioned = [v.unversioned for doi in versioned if (v := doi_version(doi)) is not None]
    targets = compute_doi_targets(rows, versioned, store.fetch_anchor_dois(unversioned))
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
    return DoiTargetStats(len(rows) + len(versioned), changed, rule_counts)
