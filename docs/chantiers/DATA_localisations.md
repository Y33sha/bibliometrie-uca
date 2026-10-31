# Chantier — Localisations

## Contexte

`source_record_locations` range les copies par enregistrement source : clé `(source_record_id, url)`. Une même adresse donnée par trois sources forme trois lignes. Elles se fusionnent à la lecture (`publication_copies`), et l'adresse unique d'un dépôt HAL est calculée à l'écriture (`merge_locations`).

La normalisation efface toutes les localisations d'un enregistrement source, puis réécrit celles que donne sa source (`LocationStore.replace_locations`). Une information ajoutée hors normalisation sur une localisation disparaît au passage suivant.

Les identifiants arXiv et PMCID d'un enregistrement source donnent une localisation (`identifier_locations`). Le DOI de l'enregistrement source n'en donne pas : seul Crossref écrit la page du DOI comme localisation. Une publication à DOI d'une autre agence (mEDRA, KISTI, JaLC, Office des publications) est donc sans localisation éditeur, même quand son DOI mène à un PDF ouvert. Exemple : la publication 78490, DOI KISTI, fermée alors que son DOI donne le PDF. Le périmètre compte 95 publications à DOI hors Crossref et DataCite.

Lecteurs et écrivains des localisations :

| Rôle | Code |
|---|---|
| Écriture | `pipeline/ingestion/common/locations.py`, `normalizer.py`, `normalize.py` |
| Écriture hors normalisation | `correction_store.py` (copies d'un dépôt HAL introuvable, embargo échu) |
| Lecture | `infrastructure/read_models/publications/copies.py` (consolidation, phase `oa_status`, fiche publication, mesure), `report_open_science.py` |
| Scripts ponctuels | `purge_descriptive_page_locations`, `canonicalize_hal_location_urls`, `backfill_best_copy_urls`, `measure_oa_floor` |

## Décisions

- `locations` : une ligne par adresse normalisée (adresse unique d'un dépôt HAL, page d'un DOI, URL d'une copie). Elle contient la plateforme et ce qui est constaté sur l'adresse : adresse du PDF et date de la vérification par doi.org.
- `source_record_locations` devient la table de liaison entre `source_records` et `locations`. Elle contient ce que déclare chaque source : ouverture, version, licence, PDF, identifiant OAI-PMH.
- La normalisation met à jour les liaisons d'un enregistrement source : ajout des nouvelles, retrait des disparues, mise à jour des autres. Une localisation sans liaison est supprimée.
- Le DOI propre d'un enregistrement source donne une localisation, `https://doi.org/<DOI>`, comme les identifiants arXiv et PMCID.
- La lecture des copies donne une copie par localisation et par publication, avec les déclarations de ses sources. Les règles d'accès et de statut lisent ces copies.
- La phase `oa_status` vérifie par doi.org les DOI des agences autres que Crossref et DataCite. Un DOI qui mène directement à un PDF donne une copie ouverte : l'adresse du PDF et la date de vérification vont sur sa localisation. Un DOI inconnu de doi.org va dans `failed_lookups`, avec la source `doi_org`.

## Phasage

### Phase 1 — Schéma

- [ ] Migration : `locations`, liaison `source_record_locations`, reprise des lignes en place. Adresse unique des dépôts HAL et retrait des pages descriptives dans la migration.
- [ ] `tables.py`, snapshot du schéma.

### Phase 2 — Écriture

- [ ] `LocationStore` : mise à jour des liaisons, suppression des localisations sans liaison.
- [ ] Localisation du DOI propre de chaque enregistrement source.
- [ ] Écritures hors normalisation (`correction_store.py`), lectures et écritures déclarées du graphe.

### Phase 3 — Lecture

- [ ] `publication_copies` : une copie par localisation et par publication.
- [ ] `report_open_science.py`.
- [ ] Scripts ponctuels devenus sans objet retirés.

### Phase 4 — Vérification par doi.org

- [ ] Tâche de la phase `oa_status` : DOI hors Crossref et DataCite, PDF obtenu, date de vérification. Recalcul du statut des publications concernées.

### Phase 5 — Documentation

- [ ] `docs/donnees/02-sources.md`, index des tables, fiches des sources.

## Questions ouvertes

- Plateforme d'une localisation donnée par deux sources de plateformes différentes (OpenAlex nomme la source, le registre reconnaît l'adresse).
- DOI de DataCite, ignorés par Unpaywall : les vérifier aussi par doi.org ?
