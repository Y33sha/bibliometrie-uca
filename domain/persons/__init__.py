"""Concept métier Personne — value objects et règles d'entité.

Sous-modules :
- `person` : aggregate root `Person`
- `merge` : fusion de deux personnes, rôles et exclusion de la personne fusionnée
- `identifier_attribution` : aggregate `IdentifierAttribution` (clé naturelle `(id_type, id_value)`)
- `identifiers` : VOs ORCID/IdHAL/IdRef + helpers de normalisation
- `name_forms` : VO `PersonNameForm`
- `contributor_name` : VO `ContributorName`, nom d'auteur tel qu'une source le donne (nom et prénom, ou chaîne brute)
- `name_matching` : compatibilité de noms entre contributions sources (`names_compatible`, `parse_raw_author_name`)
- `matching` : cascade pure de matching contribution → personne (`decide_person_match`, `decide_cross_source_match`, `decide_name_form_outcome`)
- `creation` : politique de création de personne depuis les sources (`allow_person_creation`)
"""
