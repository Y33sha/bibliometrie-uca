# Sources de données — Bibliométrie UCA

## Vue d'ensemble

Le système intègre 3 sources bibliographiques principales, complétées par des imports manuels et des APIs d'enrichissement.

| Source | Type | Couverture | API |
|--------|------|-----------|-----|
| HAL | Archive ouverte | Publications déposées par les chercheurs UCA | Solr (search) + ref/author + ref/structure |
| OpenAlex | Base bibliométrique ouverte | Publications mondiales, rattachement institutionnel par affiliation | REST (works, sources) |
| Web of Science | Base bibliométrique commerciale | Publications indexées WoS, affiliation OG | REST (Expanded API, quota annuel) |
| Unpaywall | Enrichissement OA | Statut Open Access par DOI | REST (gratuit, 100k req/jour) |
| Base RH | Import manuel | Personnel UCA (noms, départements, rôles) | Fichier CSV |
| Données APC | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV |


## HAL

### API utilisées

**Search API** (`https://api.archives-ouvertes.fr/search`) — moissonnage des publications.
- Requête par collection labo (27 collections UCA) + portail global `clermont-univ`
- Champs Solr récupérés : voir `utils/hal.py` (`HAL_FIELDS`)
- Pagination par offset, 500 résultats/page, 0.5s de délai entre requêtes

**ref/author API** (`https://api.archives-ouvertes.fr/ref/author/`) — identifiants auteurs.
- Récupération ORCID et IdRef par `hal_person_id`
- Requête par batch (100 IDs par requête)

**ref/structure API** (`https://api.archives-ouvertes.fr/ref/structure/`) — métadonnées structures.
- Enrichissement des structures HAL (dates, parents, pays, identifiants externes)
- Requête par batch (50 IDs par requête)

### Données récupérées

- **Publications** : titre, DOI, année, type de document, langue, journal, OA, URI
- **Auteurs** : nom complet, hal_person_id, idHAL, ORCID (depuis `authOrcid_s`)
- **Affiliations** : structures HAL rattachées à chaque auteur via `authIdHasStructure_fs` (pas d'adresses textuelles)
- **Collections** : `collCode_s` indique les collections auxquelles appartient le document

### Particularités

- Les champs auteurs HAL sont des tableaux alignés par position (authFullName_s[0] correspond à authOrcid_s[0], etc.)
- Le champ composite `authFullNameFormIDPersonIDIDHal_fs` contient form_id, person_id et idHAL dans un format à parser (`Nom_FacetSep_formId-personId_FacetSep_idhal`)
- Un même document peut apparaître dans plusieurs collections ; le champ `collection` en staging les agrège
- Les documents trouvés uniquement via le portail global (pas dans une collection labo) sont taggés `_portail_clermont-univ`
- Les documents cross-importés depuis OpenAlex ont `collection = NULL` (hors périmètre UCA)


## OpenAlex

### API utilisée

**Works API** (`https://api.openalex.org/works`) — moissonnage des publications.
- Requête par institution (filtre `lineage`) + année
- Pagination par cursor, 200 résultats/page, 0.2s de délai (polite pool via email)
- L'API bulk tronque les authorships à 100 auteurs ; `refetch_truncated.py` re-télécharge individuellement les works concernés

**Sources API** (`https://api.openalex.org/sources`) — enrichissement APC des journaux.
- Récupération des prix APC catalogue (DOAJ) par openalex_id

### Données récupérées

- **Publications** : titre, DOI, année, type, langue, OA status, citations, primary_location
- **Auteurs** : display_name, openalex_id, ORCID (attention : l'ORCID est sur l'entité auteur OA, pas toujours fiable pour l'authorship spécifique)
- **Affiliations** : `raw_affiliation_strings` (texte libre) + institutions structurées (openalex_id, ROR, pays)
- **Journaux/éditeurs** : source dans primary_location (titre, ISSN, type, OA model)

### Particularités

- Le `raw_author_name` de l'authorship est plus fiable que `author.display_name` (ce dernier est un nom unifié par l'algo OA, qui peut être erroné)
- Le `meta_hash` (hash hors authorships) permet de détecter les vrais changements sans être perturbé par la troncature à 100 auteurs
- Si la `primary_location` pointe vers HAL (`hal.science/hal-XXXXX`), la publication est rattachée au document HAL existant plutôt que d'en créer une nouvelle
- Les ORCID OpenAlex sont sur l'entité `openalex_authors.orcid` et utilisés avec prudence dans le pipeline persons (risque d'attribution erronée par l'algo OpenAlex)


## Web of Science

### API utilisée

**Expanded API** (`https://api.clarivate.com/api/wos`) — moissonnage des publications.
- Requête par Organisation-Enhanced (OG) + année
- Pagination par offset (`firstRecord`), 100 résultats/page, 1s de délai
- Retry avec backoff exponentiel (API instable, rate limiting silencieux)
- Quota annuel limité (vérification au démarrage)

### Données récupérées

- **Publications** : titre, DOI, année, type, langue, OA status
- **Auteurs** : display_name, last_name, first_name, daisng_id, researcher_id, ORCID
- **Affiliations** : adresses structurées dans le champ C1 (`[Author1; Author2] Address`)
- **Correspondant** : `reprint = "Y"` indique l'auteur correspondant

### Particularités

- Deux formats de données : TSV (fichiers téléchargés) et API JSON (structure imbriquée `static_data`/`dynamic_data`). Le normaliseur gère les deux.
- Le DOI est profondément imbriqué : `dynamic_data.cluster_related.identifiers.identifier[].value` (peut être dict ou liste)
- La pagination par `queryId` ne fonctionne pas de manière fiable ; le script utilise `firstRecord` avec une nouvelle recherche à chaque page
- Pause longue toutes les 10 pages (15s) et entre chaque année (30s) pour ménager l'API
- Les DOI de preprints (10.48550, 10.21203, etc.) sont filtrés lors du cross-import


## Imports manuels

### Base RH (personnel UCA)

Fichier CSV importé via `scripts/import_rh.py` → table `persons_rh`.
- Contient : nom, prénom, département, rôle, date de début/fin
- Rattaché à une personne du référentiel via `persons_rh.person_id`
- Sert de filtre dans l'annuaire personnes (filtre "Base RH")

### Données APC

Fichier CSV importé via `scripts/import_apc.py` → table `apc_payments`.
- Contient : DOI, montant, devise, éditeur, labo payeur, année
- Rattaché aux publications par DOI et aux structures par nom


## APIs d'enrichissement

### Unpaywall

Script : `processing/enrich_oa_unpaywall.py`

Interroge l'API Unpaywall (`https://api.unpaywall.org/v2/{doi}`) pour chaque publication avec DOI. Met à jour `publications.oa_status`.

Règle métier : ne remplace jamais un statut `diamond` par `gold` (Unpaywall ne distingue pas le diamond OA du gold).

### OpenAlex Sources (APC)

Script : `processing/enrich_journal_apc.py`

Interroge l'API OpenAlex Sources pour les journaux avec `openalex_id`. Récupère les prix APC catalogue (DOAJ). Met à jour `journals.apc_amount`, `apc_currency`, `is_in_doaj`.

Note : ces données ne sont pas encore exploitées en aval dans l'application.
