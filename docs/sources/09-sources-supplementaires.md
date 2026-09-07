# Sources supplémentaires

*À jour le 2026-09-07.*

Sources externes interrogées pour **enrichir** les entités du référentiel (publications, revues, éditeurs). Différence avec les sources principales : elles ne moissonnent pas, n'alimentent pas la table `staging`, et n'ont pas de `source_publications.source=...` dédié. Les données récupérées sont écrites directement sur les tables du référentiel, par la phase d'enrichissement concernée.

## Unpaywall

https://unpaywall.org/

Documentation API : https://unpaywall.org/products/api

Source d'enrichissement consultée par DOI pour obtenir une valeur à jour de `publications.oa_status`.

### API utilisée

**v2** (`https://api.unpaywall.org/v2/{doi}`) — interrogation unitaire par DOI.

- Polite pool obtenu via le paramètre `?email=...` (lue via `POLITE_POOL_EMAIL`).
- Limites Unpaywall : 100 000 requêtes/jour, ~10 req/s recommandé. L'adaptateur limite à 5 requêtes concurrentes (`asyncio.Semaphore(5)`).
- Implémentation async (`httpx2.AsyncClient`), comme tous les extracteurs unitaires par DOI (HAL/OpenAlex/WoS/ScanR/CrossRef/DataCite `fetch_missing_doi`, `fetch_truncated`).

### Données récupérées

Une seule donnée consommée : le `oa_status` du payload Unpaywall, mappé sur l'enum du référentiel : `gold`, `hybrid`, `bronze`, `green`, `closed`.

Consommée par la phase pipeline [`oa_status`](../pipeline/10-enrichissements.md#statut-open-access-oa_status).

### Particularités

**Préservation du `diamond`** — Unpaywall ne distingue pas le diamond OA du gold. L'enrichissement ne remplace **jamais** un statut `diamond` par un `gold` retourné par Unpaywall.

<!--TODO: récupérer un lien OA pour chaque publi?-->

## DOAJ

https://doaj.org/ — Directory of Open Access Journals

Source d'enrichissement des revues : « cette revue est-elle un journal open access certifié DOAJ, et à quelles conditions ? ». Consommée par `enrich_journals_from_doaj`, dans la phase [`publishers_journals`](../pipeline/05-publishers-journals.md).

### Dump utilisé

Le dump CSV public, téléchargé depuis https://doaj.org/csv. Aucun identifiant d'accès n'est requis.

L'import indexe les revues par ISSN (`issn`, `eissn`, `issnl`), remet `is_in_doaj` à FALSE partout, puis écrit `doaj_payload`, `doaj_imported_at` et `is_in_doaj` pour chaque ligne appariée. Le dump est retéléchargé quand le dernier import date de plus de trente jours.

### Données récupérées

Stockage : `journals.doaj_payload` (JSONB), `journals.doaj_imported_at` (timestamptz), `journals.is_in_doaj` (bool).

Le payload garde les colonnes du CSV pour clés. Le frontend les lit telles quelles dans `READABLE_DOAJ_FIELDS` (`"Journal title"`, `"APC amount"`…), et l'audit des frais de publication interroge `doaj_payload->>'APC amount'`.

Le script `interfaces/cli/imports/import_doaj_csv.py` importe un dump téléchargé à la main, par le même chemin d'écriture.