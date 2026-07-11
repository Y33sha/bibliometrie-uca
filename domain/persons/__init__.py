"""Concept métier Personne — value objects et règles d'entité.

Sous-modules :
- `person` : aggregate root `Person` (l'invariant de fusion vit sur `Person.can_merge_with`)
- `person_identifier` : aggregate `PersonIdentifier` (identité naturelle `(id_type, id_value)`)
- `identifiers` : VOs ORCID/IdHAL/IdRef + helpers de normalisation
- `name_forms` : VO `PersonNameForm`
- `name_matching` : compatibilité de noms entre signatures (`names_compatible`, `parse_raw_author_name`)
- `matching` : cascade pure de matching authorship → personne (`decide_person_match`, `decide_cross_source_match`, `decide_name_form_outcome`)
- `creation` : politique de création de personne depuis les sources (`allow_person_creation`)
"""
