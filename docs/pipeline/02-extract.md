# Moissonnage

*À jour le 2026-09-06.*

Récupère les données brutes depuis les API et les stocke en JSONB dans le *staging*.

## Moissonnage (`extract`)

**Critères de requête**:
- **années** de publication : de l'année de début à l'année courante. L'année de début est l'argument `--start-year`, à défaut la valeur [configurable](../guide-utilisateur/03-workflow-admin.md#années) dans `admin/config` (par défaut 2017, année de la fusion UCA) ;
- **affiliation** des publications ([périmètre configurable](../guide-utilisateur/03-workflow-admin.md#périmètres) dans `admin/config`). Il s'agit des affiliations *telles qu'elles sont renseignées dans chaque source*. Elles peuvent varier d'une source à l'autre et être incomplètes ou erronées. Ce point est géré dans les étapes ultérieures.

**Gestion des changements**:
- Chaque *payload* est hashé (MD5) pour détecter les changements lors des réexécutions. Une publication dont les métadonnées ont changé sera ré-importée et re-traitée.
- Même sans changement, `last_seen_at` est repoussée chaque fois qu'un document est revu.

## Agences d'enregistrement DOI (`resolve_ra`)

Résolution de l'agence d'enregistrement (Crossref ou DataCite, colonne `ra`) de chaque DOI, pour que [la phase suivante](#documents-absents-dune-source-fetch_missing) route chaque DOI vers la bonne API au lieu de l'interroger contre les deux.

Pour chaque préfixe pas encore résolu, interroge `doi.org/ra` et enregistre l'agence dans `doi_prefixes` (`unknown` quand elle n'est pas classée). Seuls les préfixes absents de la table `doi_prefixes` sont traités.

Une ligne `doi_prefixes` naît ici avec la seule agence d'enregistrement ; la phase [publishers_journals](05-publishers-journals.md) la complète ensuite (nom et `publisher_id` via les API `/prefixes`), une fois que `normalize` a créé les éditeurs mentionnés par les sources.

## Documents absents d'une source (`fetch_missing`)

Le moissonnage interroge les sources sur le critère de l'affiliation : un document peut être présent dans une source et ne pas être trouvé par moissonnage, si l'affiliation n'y est pas correctement renseignée. On essaie donc de retrouver dans chaque source les documents trouvés seulement dans les autres.

**Étape 1 — `fetch_missing_hal` : HAL ids manquants.**
Télécharge depuis HAL les documents référencés (par hal-id ou NNT) dans d'autres sources mais absents de notre staging. Orchestrateur dans `application/pipeline/fetch_missing/hal.py`, adaptateur HAL dans `infrastructure/sources/hal/fetch_missing_hal.py`.

**Étape 2 — `fetch_missing_doi` : DOI manquants par source.**
Pour chacune des six sources interrogeables par DOI — HAL, OpenAlex, WoS, ScanR, Crossref, DataCite —, recherche les documents présents dans les autres sources et absents de celle-ci. Orchestrateur dans `application/pipeline/fetch_missing/doi.py`, adaptateur par source dans `infrastructure/sources/<source>/fetch_missing_doi.py`. Les recherches infructueuses sont stockées dans `doi_lookups` et retentées après un délai de 30 jours.


## Documents périmés et disparus (`fetch_stale`)

Jouée à chaque exécution, cette phase rafraîchit les documents vus pour la dernière fois il y a plus de `STALE_REFRESH_AFTER_DAYS` (90 jours) et repère ceux qui ont disparu de leur source.

Chaque ligne périmée est réinterrogée par son identifiant natif : trouvée → `raw_data` rafraîchi (re-traité si l'empreinte a changé) et `last_seen_at` repoussé ; absence confirmée → `disappeared_at` posé ; erreur transitoire → laissée, retentée plus tard.

La sélection se borne aux années de la fenêtre courante, lues sur `source_publications.pub_year` — `theses` faisant exception, tout son historique restant éligible. Le seuil étale la charge : une passe ne ramasse que ce qui vient de franchir les 90 jours.

`not_found_at` marque un document que la source n'a jamais renvoyé ; `disappeared_at`, un document qu'elle rendait et qui a disparu.

`disappeared_at` est un **marqueur seul** : rien en aval ne l'exploite, ni suppression, ni exclusion, ni propagation. *TODO: cascade de suppression à construire*

## Listes d'auteurs tronquées (`fetch_truncated`)

L'[API OpenAlex](../sources/03-openalex.md) plafonne la liste des auteurs à 100 par réponse ; au-delà, les auteurs surnuméraires sont absents du payload moissonné.

Les works de 100 auteurs sont marqués à l'extraction par le flag `staging.authors_truncated`. Cette phase retélécharge un par un les works marqués, récupère la liste complète des auteurs et supprime le flag.

On ne met pas à jour `raw_hash`, qui reste l'empreinte du payload initial : tant que le moissonnage par lot renvoie le même payload, `raw_data` n'est pas écrasé.
