# OPS (Office européen des brevets)

*À jour le 2026-11-10.*

https://ops.epo.org/

Documentation API : https://www.epo.org/en/searching-for-patents/data/web-services/ops

Open Patent Services (OPS) est l'API de l'Office européen des brevets. Elle couvre les demandes et les publications de brevets de tous les offices. La source `ops` donne les brevets dont un établissement du périmètre est déposant.

Une famille de brevets réunit les demandes déposées auprès de plusieurs offices (FR, EP, WO, US…) pour une même invention. Un enregistrement source OPS est une famille INPADOC : les demandes liées par leurs priorités. Son identifiant est le numéro de la priorité la plus ancienne, c'est-à-dire de la première demande déposée pour l'invention.

Le [moissonnage](../pipeline/02-harvest.md#moissonnage-par-affiliation-harvest) cherche les publications par les graphies des déposants du périmètre, renseignées dans les `api_ids` de la structure sous leur forme de comparaison (`normalize_text`). Une publication est gardée si un déposant a exactement l'une de ces graphies et si l'année de sa priorité est dans la fenêtre du run. Le moissonnage demande ensuite la famille de chaque publication gardée.

## API utilisée

- `published-data/search/biblio` : recherche en syntaxe CQL, par déposant (`pa`), numéro de priorité (`pr`) ou numéro quelconque (`num`) ; 100 résultats par requête, 2 000 au plus par recherche ;
- `family/publication/docdb/{office}.{numéro}/biblio` : famille d'une publication ;
- `family/application/docdb/{office}.{numéro}/biblio` : famille d'une demande.

- Identifiants d'accès : clé et secret d'une application OPS (`EPO_OPS_KEY`, `EPO_OPS_SECRET`), échangés contre un jeton d'accès valable 20 minutes. Inscription gratuite sur https://developers.epo.org/, quota hebdomadaire.
- OPS limite le débit de chaque service selon sa charge. L'en-tête `X-Throttling-Control` donne l'état du service, du vert au noir. Une requête refusée pour surcharge (403 `CLIENT.RobotDetected`) est retentée après une pause.
- Débit et requêtes simultanées du pipeline : `pipeline/ingestion/api_params.py`

## Données récupérées

- **Famille** : pour chaque membre, la demande, la publication avec son code de type (A pour une demande publiée, B pour un brevet délivré), les priorités revendiquées. Titres et résumé, classification CPC sans libellé.
- **Déposants** : noms seulement.
- **Inventeurs** : noms seulement. Ce sont les contributions sources de rôle `inventor`.

## Particularités

### Numéros

Les numéros de publication (`patent_publication_number`) et de demande (`patent_application_number`) suivent le format docdb : office, puis numéro, sans code de type. Une demande internationale s'écrit sous l'office WO, sans office de dépôt (`FR2017051773` → `WO2017051773`). Une demande américaine publiée s'écrit sans le zéro qui suit l'année (`US20240211607` → `US2024211607`).

Ces numéros sont des clés de confirmation de la [réconciliation](../pipeline/07-publications.md) : un dépôt HAL de brevet rejoint ainsi sa famille. Un dépôt HAL sans famille en base cherche sa famille dans OPS par numéro, à la phase [`fetch_missing`](../pipeline/02-harvest.md#documents-absents-dune-source-fetch_missing).

### Noms des déposants et des inventeurs

OPS donne chaque nom sous deux formats : le format original et le format epodoc, abrégé et suivi du pays (`UNIV CLERMONT AUVERGNE [FR]`). Un déposant prend des graphies multiples d'un office à l'autre. Les formes de comparaison de toutes ces graphies vont dans `source_extras.patent_applicant_forms`. La phase [`affiliations`](../pipeline/04-affiliations.md) les compare aux graphies de la structure : l'indice de périmètre `patent_applicant` va alors à tous les inventeurs de la famille.

Un inventeur se rattache à une personne existante par son nom.

### Date de publication

La date de publication d'un brevet est la date de sa priorité la plus ancienne. Les dates de dépôt, de publication et de délivrance de chaque demande vont dans `source_extras`.
