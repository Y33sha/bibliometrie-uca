"""Modèles Pydantic du router des contributions admin : corps des requêtes entrantes et réponses composées après mutation."""

from pydantic import BaseModel

# ----- Corps des requêtes -----


class CreatePersonName(BaseModel):
    last_name: str
    first_name: str = ""


class SourceContributionRef(BaseModel):
    source: str
    source_contribution_id: int


class AssignOrphanContribution(BaseModel):
    """Attribution unitaire, seule à savoir créer la personne au passage.

    `source_contributions.id` est une clé primaire : l'id désigne la contribution source à lui seul.
    """

    source_contribution_id: int
    person_id: int | None = None
    create_person: CreatePersonName | None = None
    force: bool = False


class BatchAssignOrphanContributions(BaseModel):
    """Attribution en lot à une personne existante."""

    source_contribution_ids: list[int]
    person_id: int
    force: bool = False


# ----- Réponses composées par le router -----


class OrphanAssignResponse(BaseModel):
    """Acquittement de l'attribution d'une contribution source orpheline : la personne rattachée."""

    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(BaseModel):
    """Acquittement de l'attribution en lot : le nombre de contributions sources rattachées."""

    ok: bool = True
    assigned: int
