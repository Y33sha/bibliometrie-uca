# Vue d'ensemble

*À jour le 2026-10-13.*

Le système intègre 7 sources bibliographiques, des sources complémentaires et des imports manuels.

## Sources bibliographiques

| Source | Type | Couverture | API | Identifiants d'accès |
|--------|------|-----------|-----|-----|
| [HAL](02-hal.md) | Archive ouverte | Publications déposées par les chercheurs | Solr (search) | aucun |
| [OpenAlex](03-openalex.md) | Base bibliométrique ouverte | Vise l'exhaustivité sur le plan mondial | REST (works, sources, publishers) | clé API gratuite, ou adresse électronique de contact |
| [Web of Science](04-wos.md) | Base bibliométrique commerciale | Publications indexées WoS | REST (Expanded API, quota annuel) | clé API sur demande (selon contrat établissement) |
| [ScanR](05-scanr.md) | Portail du ministère de l'Enseignement supérieur et de la Recherche | Publications de l'écosystème français de la recherche | Elasticsearch (DataESR) | login et mot de passe sur demande, par le [formulaire de contact](https://scanr.enseignementsup-recherche.gouv.fr/about/contact) |
| [theses.fr](08-theses.md) | Portail officiel des thèses françaises | Thèses soutenues et en cours | REST | aucun |
| [Crossref](06-crossref.md) | Agence d'enregistrement de DOI | Publications dotées d'un [DOI](../glossaire.md#doi) Crossref. Sert aussi à trouver l'éditeur d'un préfixe DOI. | REST (works, prefixes, members) | adresse électronique de contact |
| [DataCite](07-datacite.md) | Agence d'enregistrement de DOI | Publications dotées d'un [DOI](../glossaire.md#doi) DataCite : jeux de données, logiciels, *preprints*, dépôts d'entrepôts (Zenodo, figshare, recherche-data-gouv…). Sert aussi à trouver l'entrepôt d'un préfixe DOI. | REST (dois, prefixes) | adresse électronique de contact |

Un [exemple de publication](11-exemple-de-publication.md) compare les métadonnées de cinq sources.

### Modes d'interrogation

| Source | Moissonnage par affiliation | Moissonnage par personne | Recherche par identifiant de document |
|---|---|---|---|
| HAL | collection HAL + année | ORCID, idHAL, IdRef | hal-id, NNT, DOI |
| OpenAlex | institution (filtre `lineage`) + année | ORCID | DOI |
| Web of Science | champ OG (Organization) + année | — | DOI |
| ScanR | identifiant SIREN + année | ORCID, IdRef | DOI |
| theses.fr | PPN d'établissement + année de soutenance | — | NNT |
| Crossref | — | ORCID | DOI |
| DataCite | mot-clé d'affiliation + année | ORCID | DOI |

Le moissonnage par personne interroge les identifiants des personnes RH, confirmés ou authentifiés.

## Sources complémentaires

| Source | Type | Couverture | API | Identifiants d'accès |
|--------|------|-----------|-----|-----|
| [Unpaywall](09-sources-supplementaires.md#unpaywall) | Base de statuts open access | Statut open access par DOI | REST (gratuit, 100k req/jour) | adresse électronique de contact |
| [DOAJ](09-sources-supplementaires.md#doaj) | Annuaire des revues open access certifiées | Métadonnées qualifiées par revue (licence, APC, sujets…), rattachées aux revues par ISSN | dump CSV | adresse électronique de contact |
| [Extraction RH](10-imports-manuels.md#extraction-rh) | Import manuel | Personnel de l'établissement (noms, départements, rôles) | Fichier CSV | |
| [Données APC](10-imports-manuels.md#données-apc) | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV | |
