"""Structures de recherche et d'enseignement : laboratoire, école doctorale, université, hôpital…"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict, Unpack, cast

from domain.errors import ValidationError
from domain.structures.identifiers import HalCollection, RorId
from domain.structures.name_forms import StructureNameForm


class StructureType(StrEnum):
    """Type de structure. Reflet du type PostgreSQL `structure_type`."""

    UNIVERSITE = "universite"
    CHU = "chu"
    ECOLE = "ecole"
    LABO = "labo"
    EQUIPE = "equipe"
    SITE = "site"
    ONR = "onr"
    # Service (direction des systèmes d'information, bibliothèque universitaire) ou structure fédérative (institut, sous tutelle de l'université et tutelle de laboratoires).
    ADMIN = "admin"
    AUTRE = "autre"

    @property
    def is_affiliation(self) -> bool:
        """Vrai si un rattachement à une structure de ce type est une affiliation. Les formes de nom d'un site sont celles d'un lieu (commune, campus, code postal), qui sert de contexte à la reconnaissance d'autres structures (`requires_context_of`)."""
        return self is not StructureType.SITE


def _parse_type(raw: str) -> StructureType:
    """`StructureType` depuis sa valeur textuelle ; `ValidationError` hors énumération."""
    try:
        return StructureType(raw)
    except ValueError as exc:
        raise ValidationError(f"Type de structure invalide : {raw!r}") from exc


def _parse_ror(raw: str | None) -> RorId | None:
    """`RorId` d'une valeur saisie, URL comprise ; `None` si elle est vide. Lève `ValidationError` si elle est invalide."""
    if not raw or not raw.strip():
        return None
    parsed = RorId.try_parse(raw)
    if parsed is None:
        raise ValidationError(f"ror_id invalide : {raw!r}")
    return parsed


def _parse_hal(raw: str | None) -> HalCollection | None:
    """`HalCollection` d'une valeur saisie ; `None` si elle est vide. Lève `ValidationError` si elle est invalide."""
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
    """Structure. `create` et `apply` valident son type, son ROR et sa collection HAL ; `api_ids` se valide à l'écriture en base."""

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
        """Structure à enregistrer, sans `id`."""
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
        """Applique les champs fournis, et renvoie leurs noms."""
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
