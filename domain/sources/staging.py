"""Vocabulaire de la table `staging`."""

from enum import StrEnum


class StagingEntryMode(StrEnum):
    """Voie par laquelle une ligne de `staging` est entrée, valeur de `staging.entry_mode`. Posée à la création, jamais réécrite."""

    # Moissonnage d'une source sur les affiliations du périmètre.
    BULK = "bulk"
    # Recherche par DOI d'un document trouvé dans une autre source.
    FETCH_MISSING_DOI = "fetch_missing_doi"
    # Recherche dans HAL par identifiant HAL ou NNT d'un document trouvé dans une autre source.
    FETCH_MISSING_HAL = "fetch_missing_hal"
    # Recherche dans theses.fr par NNT d'une thèse trouvée dans une autre source.
    FETCH_MISSING_THESES = "fetch_missing_theses"
    # Import d'un export de l'interface d'une source.
    MANUAL_EXPORT = "manual_export"
    # Interrogation d'une source par l'identifiant d'une personne.
    PERSON_IDENTIFIER = "person_identifier"
