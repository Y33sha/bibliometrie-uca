"""Concept métier Structure — modèles JSONB et (à terme) value objects
et entités.

Aujourd'hui ce module ne contient qu'un modèle Pydantic pour la
colonne `structures.api_ids`. Il accueillera plus tard :
- Value objects pour ROR, RNSR (identifiants d'organisation)
- Entité `Structure` si elle gagne des invariants métier
- Règles de dédoublonnage de structures

Comme pour domain/person.py et domain/publication.py : un fichier
par concept métier, on promouvra en package (`domain/structure/`) le
jour où ça dépasse ~500 lignes.
"""

from pydantic import BaseModel, ConfigDict, field_validator


class StructureApiIds(BaseModel):
    """Modèle de la colonne JSONB `structures.api_ids`.

    Identifiants API externes d'une structure, **indexés par source**.
    Chaque source peut avoir 0, 1 ou plusieurs IDs (ex. une structure
    fusionnée dans OpenAlex a parfois gardé deux entrées distinctes).
    Les valeurs sont donc des **listes de strings** pour homogénéité,
    même quand il n'y a qu'un seul ID.

    Utilisé pour configurer les filtres d'affiliation lors des
    extractions (via `utils/app_config.get_extraction_api_ids`).

    extra="allow" pour accepter les sources futures sans migration.
    """

    model_config = ConfigDict(extra="allow")

    openalex: list[str] | None = None
    wos:      list[str] | None = None
    scanr:    list[str] | None = None
    theses:   list[str] | None = None  # PPN IdRef des établissements
    hal:      list[str] | None = None  # collections HAL

    @field_validator("openalex", "wos", "scanr", "theses", "hal", mode="before")
    @classmethod
    def _ensure_list(cls, v):
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

    def to_dict(self) -> dict:
        """Sérialise pour écriture en base (JSONB). Omet les clés None
        et les listes vides."""
        return {k: v for k, v in self.model_dump(exclude_none=True).items() if v}
