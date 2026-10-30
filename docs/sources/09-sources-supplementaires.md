# Sources supplémentaires

*À jour le 2026-09-07.*

Sources consultées pour enrichir les publications, les revues et les éditeurs. Elles ne produisent pas d'enregistrement source : leurs données vont dans des tables dédiées ou dans le référentiel.

## Unpaywall

https://unpaywall.org/

Documentation API : https://unpaywall.org/products/api

Consultée par DOI pour le statut open access des publications. Les DOI DataCite, absents d'Unpaywall, sont écartés.

### API utilisée

**v2** (`https://api.unpaywall.org/v2/{doi}`) — interrogation unitaire par DOI.

- Adresse électronique de contact dans le paramètre `email` (`POLITE_POOL_EMAIL`).
- Limites Unpaywall : 100 000 requêtes/jour, ~10 req/s recommandé. Le pipeline envoie 5 requêtes simultanées.

### Données récupérées

Une seule donnée consommée : le `oa_status` du payload Unpaywall, mappé sur l'enum du référentiel : `gold`, `hybrid`, `bronze`, `green`, `closed`. La phase [`oa_status`](../pipeline/11-enrichissements.md#statut-open-access-oa_status) l'écrit par DOI dans `sources.unpaywall`, avec la date de l'interrogation. Un DOI absent d'Unpaywall y reçoit un statut nul.

### Particularités

Le verdict d'Unpaywall l'emporte sur le statut des sources, sauf dans trois cas : diamond face à gold, qu'Unpaywall ne distingue pas ; embargoed face à closed ou unknown ; dépôt en archive ouverte face à closed ou unknown.

## Sudoc

https://www.sudoc.fr/ — catalogue collectif des bibliothèques de l'enseignement supérieur (ABES)

Source de référence des ISSN des revues. Consommée par `check_serials_in_sudoc`, dans la phase [`publishing`](../pipeline/05-publishing.md).

### Services utilisés

- `https://www.sudoc.fr/services/issn2ppn/<ISSN>,<ISSN>&format=text/json` : PPN de la notice de chaque ISSN d'une revue, en une requête.
- `https://www.sudoc.fr/<ppn>.xml` : notice MARCXML.

Aucun identifiant d'accès n'est requis. Aucune limite de débit n'est documentée : le pipeline s'en tient à 5 requêtes par seconde, 4 revues à la fois (`MAX_PER_SECOND`, `SUDOC_MAX_CONCURRENT`, `pipeline/ingestion/api_params.py`). Licence ouverte Etalab.

### Données récupérées

Une notice décrit une revue sur un support : le papier, l'en ligne et le CD-ROM ont chacun leur ISSN et leur notice. Le pipeline lit dans la notice l'ISSN, l'ISSN-L, les ISSN annulés, le support et les ISSN des autres supports. Il écrit dans `serial_issns` le support, l'ISSN-L, le statut et la date de vérification de chaque ISSN.

## DOAJ

https://doaj.org/ — Directory of Open Access Journals

Indique si une revue est certifiée open access par le DOAJ, et à quelles conditions. Consommée par `enrich_serials_from_doaj`, dans la phase [`publishing`](../pipeline/05-publishing.md).

### Dump utilisé

Le dump CSV public, téléchargé depuis https://doaj.org/csv. Aucun identifiant d'accès n'est requis.

Le dump est retéléchargé quand le dernier import date de plus de trente jours, par défaut.

### Données récupérées

Stockage : `serials.doaj_payload` (JSONB), `serials.doaj_imported_at` (timestamptz), `serials.is_in_doaj` (bool).

Le payload garde les colonnes du CSV pour clés.

Un dump téléchargé à la main s'importe par le même chemin d'écriture :

```bash
uv run python -m interfaces.cli.imports.import_doaj_csv data/doaj_journalcsv_*.csv
```