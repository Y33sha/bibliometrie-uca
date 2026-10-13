"""Moissonnage des sources par l'identifiant d'une personne : identifiants acceptés par source, statuts des identifiants interrogés."""

from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.sources.registry import Source

# Identifiants de personne que chaque source sait chercher. theses.fr ne cherche par aucun.
PERSON_SEARCH_IDENTIFIERS: dict[Source, frozenset[PersonIdentifierType]] = {
    Source.HAL: frozenset(
        {PersonIdentifierType.ORCID, PersonIdentifierType.IDHAL, PersonIdentifierType.IDREF}
    ),
    Source.SCANR: frozenset({PersonIdentifierType.ORCID, PersonIdentifierType.IDREF}),
    Source.OPENALEX: frozenset({PersonIdentifierType.ORCID}),
    Source.WOS: frozenset({PersonIdentifierType.ORCID}),
    Source.CROSSREF: frozenset({PersonIdentifierType.ORCID}),
    Source.DATACITE: frozenset({PersonIdentifierType.ORCID}),
}

# Statuts d'un identifiant de personne RH qui la font interroger.
SEARCHED_IDENTIFIER_STATUSES: frozenset[AttributionStatus] = frozenset(
    {AttributionStatus.CONFIRMED, AttributionStatus.AUTHENTICATED}
)
