# backend/routers/persons.py :

`/personnes/{id}?tab=identites`

Ligne 562-572 — HAL authors détail : FROM source_authors sauth pour lister les comptes HAL liés (full_name, orcid, idhal, hal_person_id, uca_pub_count). Ici source_authors sert de table d'entités HAL — c'est légitime, on veut lister les comptes HAL distincts.

Ligne 590-598 — WoS authors détail : idem, sauth.orcid. Le JOIN reste pour l'entité auteur WoS.

`/problemes-hal`

Lignes 1588-1627 — Détection des personnes liées à 2+ comptes HAL : GROUP BY person_id HAVING COUNT(DISTINCT hal_person_id) >= 2. Requête spécifique aux comptes HAL, nécessite source_authors.

# application/persons.py :

link_authorship : dual-write person_id sur source_authors pour les comptes HAL. Légitime — tant que source_authors.person_id est utilisé ailleurs (étape 0 de create_persons, page comptes HAL).

Ligne 512 — merge_persons : transfert person_id sur source_authors.
