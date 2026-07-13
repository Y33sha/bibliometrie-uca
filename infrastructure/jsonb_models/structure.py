"""Modèle Pydantic de la colonne JSONB `structures.api_ids`."""

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class StructureApiIds(BaseModel):
    """Modèle de la colonne JSONB `structures.api_ids`.

    Identifiants API externes d'une structure, **indexés par source**.
    Chaque source peut avoir 0, 1 ou plusieurs IDs (ex. une structure
    fusionnée dans OpenAlex a parfois gardé deux entrées distinctes).
    Les valeurs sont donc des **listes de strings** pour homogénéité,
    même quand il n'y a qu'un seul ID.

    Utilisé pour configurer les filtres d'affiliation lors des
    extractions (via `infrastructure/sources/config.py`, `get_extraction_api_ids`).

    Clés strictes (whitelist `domain.sources.STRUCTURE_API_SOURCES`) :
    `extra="forbid"` rejette toute clé inconnue, par cohérence avec
    le fait que la liste des sources est une connaissance métier
    centralisée côté domain. Un test de synchronisation vérifie
    que les champs du modèle correspondent exactement à la whitelist.
    """

    model_config = ConfigDict(extra="forbid")

    openalex: list[str] | None = None
    wos: list[str] | None = None
    scanr: list[str] | None = None
    theses: list[str] | None = None  # PPN IdRef des établissements
    hal: list[str] | None = None  # collections HAL

    @field_validator("openalex", "wos", "scanr", "theses", "hal", mode="before")
    @classmethod
    def _ensure_list(cls, v: str | list[str] | None) -> list[str] | None:
        """Tolère un string unique en entrée en le wrappant en liste.

        Données historiques : certaines entrées ont pu être écrites
        avec un scalaire au lieu d'une liste. Ce validator les
        normalise au passage — le résultat final est toujours
        list[str] (ou None).
        """
        if v is None:
            return None
        if isinstance(v, str):
            return [v] if v else None
        return v

    def to_dict(self) -> dict[str, Any]:
        """Sérialise pour écriture en base (JSONB, `structures.api_ids`).
        Omet les clés None et les listes vides. `Any` justifié :
        sérialisation pour colonne JSONB libre."""
        return {k: v for k, v in self.model_dump(exclude_none=True).items() if v}
