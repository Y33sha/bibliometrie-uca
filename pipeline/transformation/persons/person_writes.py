"""Écritures de la phase `persons` sur une personne : création, nom, identifiants, rattachement d'une signature.

Les requêtes sur les personnes, leurs formes de nom et leurs identifiants sont celles du repository des personnes, que l'API utilise aussi. Les règles communes sont dans `domain.persons` : nom requis (`validated_name`), formes de nom (`compute_person_name_forms`), attribution d'un identifiant (`attribution_outcome`).
"""

import logging
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.errors import CannotAttributeConflict, ValidationError
from domain.persons.identifier_attribution import (
    AttributionOutcome,
    IdentifierAttribution,
    attribution_outcome,
)
from domain.persons.identifiers import (
    PERSON_IDENTIFIER_TYPES,
    IdentifierOrigin,
    normalized_identifier_value,
)
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person import validated_name
from domain.sources.registry import require_known_source
from domain.types import JsonValue
from infrastructure.repositories.person_repository import (
    create_person,
    find_identifier,
    insert_identifier,
    refresh_name_forms,
    update_identifier,
    update_person_name,
)

logger = logging.getLogger(__name__)

_LINK_AUTHORSHIP = text("""
    UPDATE source_authorships
    SET person_id = :pid, resolution_mode = CAST(:mode AS resolution_mode)
    WHERE id = :aid AND source = :src
""")


class IdentifierConflict(NamedTuple):
    """Une valeur d'identifiant qu'une signature du candidat contient est déjà attribuée à une autre personne.

    L'arbitrage par consensus des porteurs la transfère au candidat si le consensus le désigne. Une attribution `confirmed` n'est jamais transférée.
    """

    id_type: str
    id_value: str
    candidate_person_id: int
    owner_person_id: int
    owner_status: str


class PersonWrites:
    """Accès PostgreSQL du pipeline aux écritures sur une personne."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, last_name: str, first_name: str = "") -> int:
        """Crée une personne et retourne son `id`. Ses formes de nom sont posées par la synchronisation de fin de phase."""
        return create_person(self._conn, last_name, first_name)

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        """Change le nom d'une personne, sans toucher à ses formes de nom."""
        update_person_name(self._conn, person_id, last_name, first_name)

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        """Pose `forms` comme formes du nom de la personne (source `persons`)."""
        refresh_name_forms(self._conn, person_id, forms)

    def find_identifier(self, id_type: str, id_value: str) -> IdentifierAttribution | None:
        """L'attribution de la paire `(id_type, id_value)`, ou `None`."""
        return find_identifier(self._conn, id_type, id_value)

    def insert_identifier(self, ident: IdentifierAttribution) -> None:
        """Insère l'attribution et pose son `id`."""
        insert_identifier(self._conn, ident)

    def update_identifier(self, ident: IdentifierAttribution) -> None:
        """Écrit la personne, le statut et l'origine d'une attribution existante."""
        update_identifier(self._conn, ident)

    def link_authorship(
        self, person_id: int, source: str, source_authorship_id: int, resolution_mode: str
    ) -> None:
        """Rattache une signature à une personne, avec le canal de résolution (`identifier`, `name` ou `cross_source`). Lève `ValidationError` sur une source hors registre."""
        require_known_source(source)
        self._conn.execute(
            _LINK_AUTHORSHIP,
            {"pid": person_id, "aid": source_authorship_id, "src": source, "mode": resolution_mode},
        )


def rename_person(person_id: int, last_name: str, first_name: str, *, writes: PersonWrites) -> None:
    """Change le nom d'une personne et recalcule aussitôt ses formes de nom. Lève `ValidationError` sans patronyme."""
    last_name, first_name = validated_name(last_name, first_name)
    writes.update_name(person_id, last_name, first_name)
    writes.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))


def add_identifiers_from_authorships(
    person_id: int,
    authorships: Sequence[Mapping[str, JsonValue]],
    *,
    writes: PersonWrites,
) -> None:
    """Attribue en `pending` à la personne les identifiants observés dans ses signatures, donnés par `{id_type: valeur}`.

    Une valeur mal formée est journalisée et écartée. Une valeur déjà attribuée à une autre personne en `pending` ou `confirmed` est laissée : l'arbitrage par consensus du run suivant la tranche.
    """
    seen: set[tuple[str, str]] = set()
    for a in authorships:
        for id_type in PERSON_IDENTIFIER_TYPES:
            raw = a.get(id_type)
            if not raw:
                continue
            # `hal_person_id` arrive en int, les autres en str ; la colonne est en text.
            value = str(raw)
            if (id_type, value) in seen:
                continue
            seen.add((id_type, value))
            try:
                _add_identifier(person_id, id_type, value, writes=writes)
            except CannotAttributeConflict as exc:
                logger.debug("%s", exc)
            except ValidationError:
                logger.warning("Identifiant mal formé ignoré : %s=%r", id_type, value)


def _add_identifier(person_id: int, id_type: str, id_value: str, *, writes: PersonWrites) -> None:
    """Attribue un identifiant à la personne selon `attribution_outcome`."""
    id_value = normalized_identifier_value(id_type, id_value)
    existing = writes.find_identifier(id_type, id_value)
    outcome = attribution_outcome(existing, person_id)
    if outcome is AttributionOutcome.ADDED:
        writes.insert_identifier(
            IdentifierAttribution(
                id=None,
                person_id=person_id,
                id_type=id_type,
                id_value=id_value,
                source=IdentifierOrigin.AUTO,
            )
        )
    elif existing is not None and outcome is AttributionOutcome.REASSIGNED:
        existing.reattribute_to(person_id, source=IdentifierOrigin.AUTO)
        writes.update_identifier(existing)
