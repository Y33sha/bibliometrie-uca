"""Référentiel ROR : chargement depuis son dump, cohérence avec `structure_tutelles`."""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection

from application.ports.read_models.ror_queries import RorCoherenceQueries
from application.ports.repositories.ror_repository import RorRepository
from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, ror_relations
from domain.structures.ror_coherence import TutelleCoherence, tutelle_coherence


@dataclass(frozen=True, slots=True)
class RorImportStats:
    organizations: int
    relations: int


def import_ror_dump(
    conn: Connection,
    organizations: Iterable[RorOrganization],
    *,
    repo: RorRepository,
) -> RorImportStats:
    """Remplit le référentiel ROR avec les organisations du dump et leurs relations parent/enfant, en une transaction."""
    orgs = list(organizations)
    relations = ror_relations(orgs)
    repo.replace_all(orgs, relations)
    conn.commit()
    return RorImportStats(organizations=len(orgs), relations=len(relations))


@dataclass(frozen=True, slots=True)
class RorCoherenceReport:
    """Écarts entre les référentiels, avec le code de chaque structure et le nom de chaque organisation ROR citée."""

    coherence: TutelleCoherence
    codes: dict[int, str]
    ror_ids: dict[int, RorId]
    ror_names: dict[RorId, str]


def ror_coherence_report(queries: RorCoherenceQueries) -> RorCoherenceReport:
    """Compare `structure_tutelles` aux relations du ROR, pour toutes les structures qui ont un ROR."""
    structures = queries.structures()
    structure_rors = {s.id: s.ror_id for s in structures if s.ror_id is not None}
    coherence = tutelle_coherence(
        structure_rors=structure_rors,
        tutelles=queries.tutelles(),
        ror_edges=queries.ror_relations(),
        scope=queries.perimeter_structure_ids(),
    )
    cited = {r for _, r in coherence.outside_parents | coherence.outside_children}
    return RorCoherenceReport(
        coherence=coherence,
        codes={s.id: s.code for s in structures},
        ror_ids=structure_rors,
        ror_names=queries.ror_names(cited | coherence.shared_ror_ids),
    )
