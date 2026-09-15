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

## Sudoc

https://www.sudoc.fr/ — catalogue collectif des bibliothèques de l'enseignement supérieur (ABES)

Source de référence des ISSN des revues. Consommée par `check_journals_in_sudoc`, dans la phase [`publishers_journals`](../pipeline/05-publishers-journals.md).

### Services utilisés

- `https://www.sudoc.fr/services/issn2ppn/<ISSN>,<ISSN>&format=text/json` : PPN de la notice de chaque ISSN d'une revue, en une requête. Le format de réponse se donne dans le chemin. Une requête dont aucun ISSN n'a de notice répond 404.
- `https://www.sudoc.fr/<ppn>.xml` : notice MARCXML, lue avec `defusedxml`.

Aucun identifiant d'accès n'est requis. Aucune limite de débit n'est documentée : le pipeline s'en tient à 5 requêtes par seconde, 4 revues à la fois (`SUDOC_MAX_PER_SECOND`, `SUDOC_MAX_CONCURRENT`). Licence ouverte Etalab.

### Données récupérées

Une notice décrit une publication sur un support : l'ISSN papier et l'ISSN électronique d'une revue ont chacun leur notice. Zones lues : `011$a` (ISSN), `011$f` (ISSN-L), `011$y` (ISSN annulé), `182$c` (support : `n` papier, `c` électronique), `452$x` (ISSN de l'autre support), `200$a` (titre).

La notice elle-même n'est pas conservée. Ses informations sont écrites dans `journals.issn`, `eissn` et `issnl`, et la date de vérification dans `journals.sudoc_checked_at`.

## DOAJ

https://doaj.org/ — Directory of Open Access Journals

Source d'enrichissement des revues : « cette revue est-elle un journal open access certifié DOAJ, et à quelles conditions ? ». Consommée par `enrich_journals_from_doaj`, dans la phase [`publishers_journals`](../pipeline/05-publishers-journals.md).

### Dump utilisé

Le dump CSV public, téléchargé depuis https://doaj.org/csv. Aucun identifiant d'accès n'est requis.

L'import indexe les revues par ISSN (`issn`, `eissn`, `issnl`), remet `is_in_doaj` à FALSE partout, puis écrit `doaj_payload`, `doaj_imported_at` et `is_in_doaj` pour chaque ligne appariée. Le dump est retéléchargé quand le dernier import date de plus de trente jours.

### Données récupérées

Stockage : `journals.doaj_payload` (JSONB), `journals.doaj_imported_at` (timestamptz), `journals.is_in_doaj` (bool).

Le payload garde les colonnes du CSV pour clés. Le frontend les lit telles quelles dans `READABLE_DOAJ_FIELDS` (`"Journal title"`, `"APC amount"`…), et l'audit des frais de publication interroge `doaj_payload->>'APC amount'`.

Un dump téléchargé à la main s'importe par le même chemin d'écriture :

```bash
python -m interfaces.cli.imports.import_doaj_csv data/doaj_journalcsv_*.csv
```