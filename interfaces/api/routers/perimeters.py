"""Router des ensembles de structures que les phases du pipeline consomment. Sert `/api/perimeters/*`.

Un périmètre (table `perimeters`) nomme des structures racines dans sa colonne `structure_ids`. L'ensemble effectif y ajoute leurs descendants par `est_tutelle_de`, à l'exclusion de `est_partenaire_de` : un partenaire n'entre pas dans le périmètre de sa contrepartie. Cet ensemble est matérialisé dans `perimeter_structures` par `refresh_perimeter_structures` ; les lectures le restituent sans le recalculer.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from application.ports.api.config_queries import ConfigQueries
from application.ports.api.perimeters_queries import PerimeterOut, PerimetersQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from application.services.perimeters import commands as perimeter_commands
from interfaces.api.deps import (
    audit_repo,
    config_queries,
    db_conn,
    perimeter_repo,
    perimeters_queries,
)
from interfaces.api.models import (
    CreatedIdResponse,
    OkResponse,
    PerimeterCreate,
)

router = APIRouter(prefix="/api/perimeters", tags=["perimeters"])


@router.get("", response_model=list[PerimeterOut])
def list_perimeters(
    queries: PerimetersQueries = Depends(perimeters_queries),
) -> list[PerimeterOut]:
    """Liste les périmètres avec leurs structures racines.

    `structures` porte les seules racines ; `structure_count` compte l'ensemble effectif, racines et descendants par `est_tutelle_de` réunis.
    """
    return queries.list_perimeters_with_structures()


@router.post("", response_model=CreatedIdResponse)
def create_perimeter(
    body: PerimeterCreate,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
) -> CreatedIdResponse:
    """Crée un périmètre avec ses structures racines, la liste pouvant être vide.

    Le code sert d'identifiant naturel — la configuration du pipeline désigne un périmètre par sa valeur — et doit être un jeton unique, sans espace : un code vide ou espacé rend 422. Renvoie 409 sur un code déjà pris.
    """
    pid = perimeter_commands.create_perimeter(
        conn, code=body.code, name=body.name, structure_ids=body.structure_ids, repo=repo
    )
    return CreatedIdResponse(id=pid)


@router.put("/{perimeter_id}", response_model=OkResponse)
def update_perimeter(
    perimeter_id: int,
    body: PerimeterUpdate,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
) -> OkResponse:
    """Met à jour un périmètre (nom, structures racines).

    Seuls les champs fournis sont écrits ; un corps vide rend 400, un périmètre inconnu 404. La clôture matérialisée suit le changement de racines.
    """
    perimeter_commands.update_perimeter(conn, perimeter_id, update=body, repo=repo)
    return OkResponse()


@router.delete("/{perimeter_id}", response_model=OkResponse)
def delete_perimeter(
    perimeter_id: int,
    conn: Connection = Depends(db_conn),
    repo: PerimeterRepository = Depends(perimeter_repo),
    config: ConfigQueries = Depends(config_queries),
    audit: AuditRepository = Depends(audit_repo),
) -> OkResponse:
    """Supprime un périmètre.

    Renvoie 409 si une clé de configuration le désigne encore — le pipeline s'y appuierait sans le trouver. Les lignes de la clôture matérialisée s'en vont avec lui, par cascade.
    """
    perimeter_commands.delete_perimeter(
        conn, perimeter_id, repo=repo, config=config, audit_repo=audit
    )
    return OkResponse()
