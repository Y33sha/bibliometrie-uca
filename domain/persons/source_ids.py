"""Modèle Pydantic de la colonne JSONB ``source_persons.source_ids``.

Distinct des VOs d'identifiants (``domain.persons.identifiers``) :
ici on modélise la *colonne JSONB* qui stocke les identifiants
**bruts** lus depuis les API sources (principalement HAL). Les VOs
d'identifiants (ORCID/IdHAL/IdRef) modélisent quant à eux les types
canoniques de l'enregistrement consolidé côté ``person_identifiers``.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from domain.persons.identifiers import IdHAL


class PersonSourceIds(BaseModel):
    """Modèle de la colonne JSONB `source_ids` de `source_persons`.

    Identifiants **bruts** lus depuis les API sources (principalement
    HAL). Distinct de la table `person_identifiers` qui stocke le
    référentiel canonique (ORCID/idHAL/IdRef confirmés ou en attente,
    attachés à une personne consolidée).

    Ici on a par exemple :
    - `hal_person_id` : entier interne HAL (>0 = compte confirmé)
    - `idhal` : login slug HAL (validé via VO IdHAL)
    - `hal_form_id` : ID de la forme de nom (chaîne de caractères)

    extra="allow" pour accepter d'autres clés que d'autres sources
    (ScanR, WoS, …) pourraient introduire à l'avenir.
    """

    model_config = ConfigDict(extra="allow")

    hal_person_id: int | None = None
    idhal: str | None = None
    hal_form_id: int | None = None

    @field_validator("idhal", mode="before")
    @classmethod
    def _normalize_idhal(cls, v: str | None) -> str | None:
        """Normalise via le VO IdHAL : trim, lowercase, validation du slug."""
        if v is None or v == "":
            return None
        normalized = IdHAL.try_parse(v)
        if normalized is None:
            raise ValueError(f"IdHAL invalide : {v!r}")
        return normalized.value

    def to_dict(self) -> dict[str, Any]:
        """Sérialise pour écriture en base (JSONB). Omet les clés None.
        `Any` justifié : sortie destinée à une colonne JSONB."""
        return self.model_dump(exclude_none=True)
