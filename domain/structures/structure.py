"""Aggregate root `Structure` — entité métier d'une structure de recherche / d'enseignement (laboratoire, école doctorale, université, hôpital, …).

Identité = `id` (clé surrogate) ; identifiant naturel : `code` (unique). Une structure agrège ses formes de noms (`name_forms`), ses identifiants externes (`RorId`, `HalCollection`) et un dict `api_ids` JSONB pour les identifiants de sources sans VO dédié (clés : `openalex`, `wos`, `scanr`, `theses`, `hal`).

Les règles métier des structures (matching des formes de nom, hiérarchie `structure_relations`) vivent dans les modules voisins du package `domain/structures/`.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from domain.errors import ValidationError
from domain.structures.identifiers import HalCollection, RorId
from domain.structures.name_forms import StructureNameForm


class StructureType(StrEnum):
    """Type d'une structure de recherche / d'enseignement.

    Mappe sur l'enum Postgres `structure_type`. `StrEnum` garde la valeur sérialisable telle quelle vers SQL et API.
    """

    UNIVERSITE = "universite"
    CHU = "chu"
    ECOLE = "ecole"
    LABO = "labo"
    EQUIPE = "equipe"
    SITE = "site"
    ONR = "onr"
    # Structure administrative : service (direction des systèmes d'information, bibliothèque
    # universitaire) ou structure fédérative intermédiaire (institut, sous tutelle de l'université
    # et tutelle de laboratoires).
    ADMIN = "admin"
    AUTRE = "autre"

    @property
    def is_affiliation(self) -> bool:
        """Vrai si un rattachement à une structure de ce type constitue une affiliation.

        Un site porte les formes de nom d'un lieu — communes, campus, codes postaux — pour servir de contexte de reconnaissance à d'autres structures, via `structure_name_forms.requires_context_of`. Une adresse qui le mentionne atteste d'un lieu, non d'un rattachement institutionnel : le site est un instrument du matching, jamais son résultat.
        """
        return self is not StructureType.SITE


def _parse_type(raw: str) -> StructureType:
    """`StructureType` depuis sa valeur textuelle ; `ValidationError` hors énumération."""
    try:
        return StructureType(raw)
    except ValueError as exc:
        raise ValidationError(f"Type de structure invalide : {raw!r}") from exc


def _parse_ror(raw: str | None) -> RorId | None:
    """`RorId` canonique depuis une forme quelconque (URL comprise), `None` si vide, `ValidationError` si non vide et invalide."""
    if not raw or not raw.strip():
        return None
    parsed = RorId.try_parse(raw)
    if parsed is None:
        raise ValidationError(f"ror_id invalide : {raw!r}")
    return parsed


def _parse_hal(raw: str | None) -> HalCollection | None:
    """`HalCollection` canonique, `None` si vide, `ValidationError` si non vide et invalide."""
    if not raw or not raw.strip():
        return None
    parsed = HalCollection.try_parse(raw)
    if parsed is None:
        raise ValidationError(f"hal_collection invalide : {raw!r}")
    return parsed


@dataclass(slots=True)
class Structure:
    """Structure de recherche / d'enseignement (aggregate root).

    Garde ses invariants : `structure_type` dans l'énumération, `ror_id` et `hal_collection` sous forme canonique validée. `create` fabrique une structure neuve, `apply` applique une mise à jour partielle ; les deux valident. La validation du JSONB `api_ids` reste à la frontière de persistance (schéma Pydantic hors domaine).
    """

    id: int | None
    code: str
    name: str
    structure_type: StructureType
    acronym: str | None = None
    ror_id: RorId | None = None
    rnsr_id: str | None = None
    hal_collection: HalCollection | None = None
    api_ids: dict[str, list[str]] | None = None
    name_forms: tuple[StructureNameForm, ...] = field(default=())

    @classmethod
    def create(
        cls,
        *,
        code: str,
        name: str,
        structure_type: str,
        acronym: str | None = None,
        ror_id: str | None = None,
        rnsr_id: str | None = None,
        hal_collection: str | None = None,
        api_ids: dict[str, str | list[str]] | None = None,
    ) -> "Structure":
        """Fabrique une structure neuve (`id` non encore attribué) en validant ses champs."""
        return cls(
            id=None,
            code=code,
            name=name,
            structure_type=_parse_type(structure_type),
            acronym=acronym,
            ror_id=_parse_ror(ror_id),
            rnsr_id=rnsr_id,
            hal_collection=_parse_hal(hal_collection),
            api_ids=cast("dict[str, list[str]] | None", api_ids),
        )

    def apply(
        self,
        *,
        name: str | None = None,
        acronym: str | None = None,
        structure_type: str | None = None,
        ror_id: str | None = None,
        rnsr_id: str | None = None,
        hal_collection: str | None = None,
        api_ids: dict[str, str | list[str]] | None = None,
    ) -> list[str]:
        """Applique les champs fournis (non `None`), validés, et retourne les noms de colonnes modifiées. Une valeur `None` signifie « champ non fourni » : la mise à jour n'efface pas un champ."""
        applied: list[str] = []
        if name is not None:
            self.name = name
            applied.append("name")
        if acronym is not None:
            self.acronym = acronym
            applied.append("acronym")
        if structure_type is not None:
            self.structure_type = _parse_type(structure_type)
            applied.append("structure_type")
        if ror_id is not None:
            self.ror_id = _parse_ror(ror_id)
            applied.append("ror_id")
        if rnsr_id is not None:
            self.rnsr_id = rnsr_id
            applied.append("rnsr_id")
        if hal_collection is not None:
            self.hal_collection = _parse_hal(hal_collection)
            applied.append("hal_collection")
        if api_ids is not None:
            self.api_ids = cast("dict[str, list[str]] | None", api_ids)
            applied.append("api_ids")
        return applied
