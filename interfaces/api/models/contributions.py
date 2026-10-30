"""Modèles Pydantic du router des contributions admin : corps des requêtes entrantes et réponses composées après mutation."""

from typing import Self

from pydantic import model_validator

from application.ports.model import Model

# ----- Corps des requêtes -----


class CreatePersonName(Model):
    last_name: str
    first_name: str = ""


class SourceContributionRef(Model):
    source: str
    source_contribution_id: int


class AssignOrphanContribution(Model):
    """Attribution d'une contribution orpheline, désignée par son identifiant. Seule à pouvoir créer la personne au passage."""

    contribution_id: int
    person_id: int | None = None
    create_person: CreatePersonName | None = None
    force: bool = False

    @model_validator(mode="after")
    def _designe_une_personne(self) -> Self:
        """Vérifie que l'attribution vise une personne : la requête la désigne, ou fournit de quoi la créer."""
        if self.person_id is None and self.create_person is None:
            raise ValueError("person_id ou create_person requis")
        return self


class BatchAssignOrphanContributions(Model):
    """Attribution en lot de contributions orphelines, désignées par leurs identifiants, à une personne existante."""

    contribution_ids: list[int]
    person_id: int
    force: bool = False


# ----- Réponses composées par le router -----


class OrphanAssignResponse(Model):
    """Acquittement de l'attribution d'une contribution orpheline : la personne rattachée."""

    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(Model):
    """Acquittement de l'attribution en lot : le nombre de contributions rattachées."""

    ok: bool = True
    assigned: int
