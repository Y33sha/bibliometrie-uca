"""Données du statut open access d'un lot de publications, lues en base, et calcul du statut (`domain.publications.open_access`).

La consolidation des publications lit ces données par `oa_inputs`.
"""

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.access import Copy
from domain.publications.oa_status import OaStatus
from domain.publications.open_access import (
    has_oa_status,
    is_restricted,
    publication_oa_status,
)
from domain.serials.oa_model_history import (
    DOAJ_OPEN_LICENSE_SINCE_KEY,
    OaModelHistory,
    doaj_year,
)
from domain.serials.serial import OaModel
from domain.types import JsonValue
from infrastructure.read_models.publications.copies import publication_copies
from infrastructure.sql_fragments import under_active_embargo


class OaFacts(NamedTuple):
    """Champs d'une publication lus par le calcul de son statut open access."""

    id: int
    doi: str | None
    """DOI normalisé, clé de la table `dois`."""
    serial_id: int | None
    doc_type: str | None
    source_extras: Mapping[str, JsonValue] | None
    publication_year: int | None


class OaInputs(NamedTuple):
    """Données du calcul du statut open access d'une publication."""

    applicable: bool
    """Le statut open access s'applique au type de la publication (`has_oa_status`)."""
    has_serial: bool
    serial_oa_model: str | None
    """Modèle open access de la revue l'année de parution de la publication (`OaModelHistory.model_at`)."""
    embargoed: bool
    """Un enregistrement source de la publication est sous embargo actif."""
    restricted: bool
    """La publication est fermée par nature (`is_restricted`)."""
    unpaywall: str | None
    """Verdict d'Unpaywall sur le DOI de la publication, `None` sans verdict."""
    copies: list[Copy]

    def status(self) -> OaStatus:
        """Renvoie le statut open access déduit de ces données (`publication_oa_status`)."""
        return publication_oa_status(
            self.copies,
            applicable=self.applicable,
            embargoed=self.embargoed,
            restricted=self.restricted,
            unpaywall=self.unpaywall,
            has_serial=self.has_serial,
            serial_oa_model=self.serial_oa_model,
        )


def oa_inputs(conn: Connection, publications: Sequence[OaFacts]) -> dict[int, OaInputs]:
    """Renvoie les données du statut open access de chaque publication, par identifiant."""
    ids = [p.id for p in publications]
    serial_ids = sorted({p.serial_id for p in publications if p.serial_id is not None})
    dois = sorted({p.doi for p in publications if p.doi})
    histories = _serial_oa_histories(conn, serial_ids) if serial_ids else {}
    unpaywall = _unpaywall_verdicts(conn, dois) if dois else {}
    embargoed = _embargoed_publications(conn, ids)
    copies = publication_copies(conn, ids)
    return {
        p.id: OaInputs(
            applicable=has_oa_status(p.doc_type),
            has_serial=p.serial_id is not None,
            serial_oa_model=(
                history.model_at(p.publication_year)
                if p.serial_id is not None and (history := histories.get(p.serial_id))
                else None
            ),
            embargoed=p.id in embargoed,
            restricted=is_restricted(p.doc_type, p.source_extras),
            unpaywall=unpaywall.get(p.doi) if p.doi else None,
            copies=copies.get(p.id, []),
        )
        for p in publications
    }


def _serial_oa_histories(conn: Connection, serial_ids: Sequence[int]) -> dict[int, OaModelHistory]:
    rows = conn.execute(
        text(
            "SELECT id, oa_model::text AS oa_model, openalex_is_oa, openalex_oa_flip_year,"
            " doaj_payload->>:doaj_key AS doaj_since FROM serials WHERE id = ANY(:ids)"
        ),
        {"ids": list(serial_ids), "doaj_key": DOAJ_OPEN_LICENSE_SINCE_KEY},
    )
    return {
        r.id: OaModelHistory(
            model=OaModel(r.oa_model) if r.oa_model else None,
            openalex_is_oa=r.openalex_is_oa,
            openalex_flip_year=r.openalex_oa_flip_year,
            doaj_since_year=doaj_year(r.doaj_since),
        )
        for r in rows
    }


def _unpaywall_verdicts(conn: Connection, dois: Sequence[str]) -> dict[str, str | None]:
    rows = conn.execute(
        text("SELECT doi, unpaywall_oa_status::text AS verdict FROM dois WHERE doi = ANY(:dois)"),
        {"dois": list(dois)},
    )
    return {r.doi: r.verdict for r in rows}


def _embargoed_publications(conn: Connection, publication_ids: Sequence[int]) -> set[int]:
    rows = conn.execute(
        text(
            "SELECT DISTINCT sr.publication_id FROM source_records sr"
            f" WHERE sr.publication_id = ANY(:ids) AND {under_active_embargo('sr')}"
        ),
        {"ids": list(publication_ids)},
    )
    return set(rows.scalars())
