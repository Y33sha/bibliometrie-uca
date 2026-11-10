"""Modèle Pydantic de la colonne JSONB `structures.api_ids`."""

from pydantic import ConfigDict, field_validator

from domain.normalize import normalize_text
from infrastructure.jsonb_models._base import JsonbModel


class StructureApiIds(JsonbModel):
    """Identifiants d'une structure auprès des API externes (`structures.api_ids`), par source.

    Chaque source donne une liste d'identifiants, même pour un seul : une structure fusionnée dans OpenAlex garde parfois deux entrées. Les identifiants alimentent les filtres d'affiliation du moissonnage (`get_extraction_api_ids`).

    Les clés sont celles de `domain.sources.STRUCTURE_API_SOURCES`. `extra="forbid"` rejette une clé inconnue. Un test vérifie l'accord des champs avec cette liste.
    """

    model_config = ConfigDict(extra="forbid")

    openalex: list[str] | None = None
    wos: list[str] | None = None
    scanr: list[str] | None = None
    ops: list[str] | None = None
    """Graphies du nom de la structure parmi les déposants de brevets, sous leur forme de comparaison (`normalize_text`) : termes de recherche dans OPS et noms reconnus comme la structure."""
    theses: list[str] | None = None
    """PPN IdRef des établissements."""
    datacite: list[str] | None = None
    """Mots-clés cherchés dans les affiliations des créateurs."""
    inspire: list[str] | None = None
    """Numéros d'institution INSPIRE-HEP, à défaut noms d'affiliation cherchés en texte."""

    @field_validator(
        "openalex", "wos", "scanr", "ops", "theses", "datacite", "inspire", mode="before"
    )
    @classmethod
    def _ensure_list(cls, v: str | list[str] | None) -> list[str] | None:
        """Met en liste une chaîne seule."""
        if v is None:
            return None
        if isinstance(v, str):
            return [v] if v else None
        return v

    @field_validator("ops")
    @classmethod
    def _normalize_names(cls, v: list[str] | None) -> list[str] | None:
        """Ramène chaque graphie à sa forme de comparaison, sans doublon."""
        if v is None:
            return None
        return list(dict.fromkeys(n for name in v if (n := normalize_text(name)))) or None

    def to_dict(self) -> dict[str, list[str]]:
        """Sérialise pour l'écriture en base, sans les clés nulles ni les listes vides."""
        return {k: v for k, v in self.model_dump(exclude_none=True).items() if v}
