"""Aggregate root `Structure` — entité métier d'une structure de recherche / d'enseignement (laboratoire, école doctorale, université, hôpital, …).

Clé surrogate : `id` ; identifiant naturel : `code` (unique). Une structure agrège ses formes de noms (`name_forms`), ses identifiants externes (`RorId`, `HalCollection`) et un dict `api_ids` JSONB pour les identifiants de sources sans VO dédié (clés : `openalex`, `wos`, `scanr`, `theses`, `datacite`).

Les règles métier des structures (matching des formes de nom, hiérarchie `structure_parents`) vivent dans les modules voisins du package `domain/structures/`.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict, Unpack, cast

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


class StructureEdit(TypedDict, total=False):
    """Mise à jour partielle d'une structure. Une clé absente désigne un champ non fourni ; `None` efface la valeur."""

    name: str
    structure_type: str
    acronym: str | None
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, str | list[str]] | None


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
    ) -> Structure:
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

    def apply(self, **changes: Unpack[StructureEdit]) -> list[str]:
        """Applique les champs fournis, validés, et retourne leurs noms."""
        if "name" in changes:
            self.name = changes["name"]
        if "structure_type" in changes:
            self.structure_type = _parse_type(changes["structure_type"])
        if "acronym" in changes:
            self.acronym = changes["acronym"]
        if "ror_id" in changes:
            self.ror_id = _parse_ror(changes["ror_id"])
        if "rnsr_id" in changes:
            self.rnsr_id = changes["rnsr_id"]
        if "hal_collection" in changes:
            self.hal_collection = _parse_hal(changes["hal_collection"])
        if "api_ids" in changes:
            self.api_ids = cast("dict[str, list[str]] | None", changes["api_ids"])
        return list(changes)
