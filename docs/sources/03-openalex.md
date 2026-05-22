# OpenAlex

## API utilisée

https://developers.openalex.org/

**Works API** (https://api.openalex.org/works) — moissonnage des publications.
- Requête par institution (filtre `lineage`) + année
- Pagination par cursor, 200 résultats/page, 0.2s de délai (clé API gratuite)
- L'API bulk tronque les authorships à 100 auteurs ; [infrastructure/sources/openalex/refetch_truncated.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/infrastructure/sources/openalex/refetch_truncated.py) re-télécharge individuellement les works concernés

**Sources API** (https://api.openalex.org/sources) — enrichissement APC des journaux.
- Récupération des prix APC catalogue (DOAJ) par openalex_id

## Données récupérées

- **Publications** : titre, DOI, année, type, langue, OA status, citations, primary_location
- **Auteurs** : display_name, openalex_id, ORCID (attention : l'ORCID est sur l'entité auteur OA, pas toujours fiable pour l'authorship spécifique)
- **Affiliations** : `raw_affiliation_strings` (texte libre) + institutions structurées (openalex_id, ROR, pays)
- **Journaux/éditeurs** : source dans primary_location (titre, ISSN, type, OA model)

## Particularités

- Le `raw_author_name` de l'authorship est plus fiable que `author.display_name` (ce dernier est un nom unifié par l'algo OA, qui peut être erroné)
- La préservation des listes d'auteurs complètes obtenues par `refetch_truncated` repose sur une dissymétrie volontaire : le refetch met à jour `raw_data` mais **pas** `raw_hash`, qui reste le hash du payload bulk initial. Tant que le bulk renvoie le même payload, l'UPSERT ne touche pas `raw_data` (qui contient pourtant la liste complète). Si le bulk change, l'écrasement déclenche un re-refetch au sein du même run pipeline (refetch tourne en fin de phase extract, juste avant cross_imports).
- Si la `primary_location` pointe vers HAL (`hal.science/hal-XXXXX`), la publication est rattachée au document HAL existant plutôt que d'en créer une nouvelle
- Les ORCIDs OpenAlex sont sur `source_authorships.identifiers->>'orcid'` et utilisés avec prudence dans le pipeline persons (risque d'attribution erronée par l'algo OpenAlex — le matching nominal est appliqué avant de promouvoir un ORCID en `confirmed`)

## Enrichissement APC

*En cours de retrait : sera remplacé par DOAJ (voir [Imports manuels](imports-manuels#doaj)).*

Script : [interfaces/cli/pipeline/enrich_journal_apc.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/interfaces/cli/pipeline/enrich_journal_apc.py) (orchestration dans [application/pipeline/enrich/enrich_journal_apc.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/application/pipeline/enrich/enrich_journal_apc.py)).

Interroge l'API OpenAlex Sources pour les journaux avec `openalex_id`. Récupère les prix APC catalogue (DOAJ). Met à jour `journals.apc_amount`, `apc_currency`, `is_in_doaj`.

Note : ces données ne sont pas encore exploitées en aval dans l'application.
