"""Écritures de la phase `persons` sur une personne : création, nom, identifiants, rattachement d'une signature.

L'API a ses propres écritures sur les mêmes tables. Les règles communes sont dans `domain.persons` : nom requis (`validated_name`), formes de nom (`compute_person_name_forms`), attribution d'un identifiant (`attribution_outcome`).
"""

import logging
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.errors import CannotAttributeConflict, ValidationError
from domain.normalize import normalize_name
from domain.persons.identifier_attribution import (
    AttributionOutcome,
    IdentifierAttribution,
    attribution_outcome,
)
from domain.persons.identifiers import (
    PERSON_IDENTIFIER_TYPES,
    AttributionStatus,
    IdentifierOrigin,
    normalized_identifier_value,
)
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE, compute_person_name_forms
from domain.persons.person import validated_name
from domain.sources.registry import require_known_source
from domain.types import JsonValue
from infrastructure.db.scalars import row_int, scalar_int

logger = logging.getLogger(__name__)

_INSERT_PERSON = text("""
    INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
    VALUES (:ln, :fn, :lnn, :fnn) RETURNING id
""")

_UPDATE_NAME = text("""
    UPDATE persons SET last_name = :ln, first_name = :fn,
                       last_name_normalized = :lnn, first_name_normalized = :fnn
    WHERE id = :id
""")

# Les formes du nom de la personne (source `persons`) sont retirées, puis posées de nouveau. Une
# forme attestée par une autre source reste.
_REMOVE_CANONICAL_FORMS = text("""
    UPDATE person_name_forms SET sources = array_remove(sources, :src)
    WHERE person_id = :pid AND :src = ANY(sources)
""")
_DELETE_EMPTY_FORMS = text(
    "DELETE FROM person_name_forms WHERE person_id = :pid AND sources = '{}'"
)
_ADD_CANONICAL_FORM = text("""
    INSERT INTO person_name_forms (name_form, person_id, sources, status)
    VALUES (:nf, :pid, ARRAY[:src], 'pending'::identifier_status)
    ON CONFLICT (name_form, person_id) DO UPDATE SET
        sources = (
            SELECT COALESCE(array_agg(DISTINCT s ORDER BY s), '{}'::text[])
            FROM unnest(person_name_forms.sources || EXCLUDED.sources) AS s
        )
""")

_FIND_IDENTIFIER = text("""
    SELECT id, person_id, id_type, id_value, source, CAST(status AS text) AS status
    FROM person_identifiers
    WHERE id_type = :it AND id_value = :iv
""")

_INSERT_IDENTIFIER = text("""
    INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
    VALUES (:pid, :it, :iv, :src, CAST(:st AS identifier_status))
    RETURNING id
""")

_UPDATE_IDENTIFIER = text("""
    UPDATE person_identifiers
    SET person_id = :pid, status = CAST(:st AS identifier_status), source = :src
    WHERE id = :id
""")

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
        return scalar_int(
            self._conn.execute(
                _INSERT_PERSON,
                {
                    "ln": last_name,
                    "fn": first_name,
                    "lnn": normalize_name(last_name),
                    "fnn": normalize_name(first_name),
                },
            )
        )

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        """Change le nom d'une personne, sans toucher à ses formes de nom."""
        self._conn.execute(
            _UPDATE_NAME,
            {
                "ln": last_name,
                "fn": first_name,
                "lnn": normalize_name(last_name),
                "fnn": normalize_name(first_name),
                "id": person_id,
            },
        )

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        """Pose `forms` comme formes du nom de la personne (source `persons`)."""
        params = {"pid": person_id, "src": CANONICAL_NAME_FORM_SOURCE}
        self._conn.execute(_REMOVE_CANONICAL_FORMS, params)
        self._conn.execute(_DELETE_EMPTY_FORMS, {"pid": person_id})
        for form in forms:
            self._conn.execute(_ADD_CANONICAL_FORM, {**params, "nf": form})

    def find_identifier(self, id_type: str, id_value: str) -> IdentifierAttribution | None:
        """L'attribution de la paire `(id_type, id_value)`, ou `None`."""
        row = self._conn.execute(_FIND_IDENTIFIER, {"it": id_type, "iv": id_value}).first()
        if row is None:
            return None
        return IdentifierAttribution(
            id=row.id,
            person_id=row.person_id,
            id_type=row.id_type,
            id_value=row.id_value,
            status=AttributionStatus(row.status),
            source=IdentifierOrigin(row.source),
        )

    def insert_identifier(self, ident: IdentifierAttribution) -> None:
        """Insère l'attribution et pose son `id`."""
        row = self._conn.execute(
            _INSERT_IDENTIFIER,
            {
                "pid": ident.person_id,
                "it": ident.id_type,
                "iv": ident.id_value,
                "src": ident.source,
                "st": ident.status.value,
            },
        ).one()
        ident.id = row_int(row.id)

    def update_identifier(self, ident: IdentifierAttribution) -> None:
        """Écrit la personne, le statut et l'origine d'une attribution existante."""
        if ident.id is None:
            raise ValueError("update_identifier : ident.id doit être posé")
        self._conn.execute(
            _UPDATE_IDENTIFIER,
            {
                "id": ident.id,
                "pid": ident.person_id,
                "st": ident.status.value,
                "src": ident.source,
            },
        )

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
