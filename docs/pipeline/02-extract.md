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

Résolution de l'agence d'enregistrement (Crossref ou DataCite) de chaque DOI, pour que [la recherche par DOI](#documents-absents-dune-source-fetch_missing) route chaque DOI vers la bonne API au lieu de l'interroger contre les deux.

Crossref et DataCite gèrent des ensembles de DOI disjoints. Sans la RA du préfixe, chaque DOI candidat devrait être tenté contre les deux API, générant 50% d'erreurs 404.

Pour chaque préfixe pas encore résolu, interroge `doi.org/ra` et enregistre la RA dans `doi_prefixes` (`unknown` quand elle n'est pas classée). Auto-bornée : seuls les préfixes absents de `doi_prefixes` sont traités, donc la phase converge. Le pool de DOI candidats est défini une seule fois par la vue `candidate_dois` — union du *staging*, des DOI liés (`related_dois`) des `source_publications`, des cibles de `publication_relations` et des DOI DataCite dérivés d'arXiv —, consommée à l'identique ici et par l'import croisé, qui ne peuvent donc pas diverger.

Une row `doi_prefixes` naît ici avec sa seule RA ; le [volet éditeur](05-publishers-journals.md) la complète ensuite (nom et `publisher_id` via les API `/prefixes`), une fois que `normalize` a créé les éditeurs mentionnés par les sources.

## Documents absents d'une source (`fetch_missing`)

Le moissonnage interroge les sources sur le critère de l'affiliation : un document peut être présent dans une source et ne pas être trouvé par moissonnage, si l'affiliation n'y est pas correctement renseignée. On essaie donc de retrouver dans chaque source les documents trouvés seulement dans les autres.

**Étape 1 — `fetch_missing_hal` : HAL ids manquants.**
Télécharge depuis HAL les documents référencés (par hal-id ou NNT) dans d'autres sources mais absents de notre staging HAL. Orchestrateur dans `application/pipeline/fetch_missing/hal.py`, adaptateur HAL dans `infrastructure/sources/hal/fetch_missing_hal.py`. Auto-borné, tourne dans tous les modes : les hal-ids/NNT introuvables sont marqués `not_found_at` dans staging et ne sont jamais re-interrogés (HAL = source native pour les hal-ids, un 404 est définitif).

**Étape 2 — `fetch_missing_doi` : DOI manquants par source.**
Pour chacune des six sources interrogeables par DOI — HAL, OpenAlex, WoS, ScanR, Crossref, DataCite —, recherche les documents présents dans les autres sources et absents de celle-ci. La plupart sont effectivement absents ; certains sont repêchés (cause : affiliations différentes selon source). Dispatcher dans `application/pipeline/fetch_missing/doi.py`, adaptateur par source dans `infrastructure/sources/<source>/fetch_missing_doi.py`. Le mode d'exécution décide des sources retenues (`application/pipeline/modes.py`), et `doi_lookups` borne le lot en écartant les DOI dont la tentative précédente est trop récente.

**Les deux étapes sont auto-bornées.** Un hal-id ou un NNT introuvable dans HAL est marqué `not_found_at` dans le staging : HAL en est la source native, et un 404 y est définitif. Chaque DOI cherché en vain est enregistré dans `doi_lookups`. Absent de sa source native, Crossref ou DataCite, il n'est jamais retenté — `next_retry` reste NULL. Absent d'une autre source, il l'est après trente jours, le temps qu'elle l'indexe peut-être. La première passe tente tout ; les suivantes reprennent les DOI neufs et ceux dont le délai est écoulé.


## Documents périmés et disparus (`fetch_stale`)

Jouée à chaque exécution, cette phase rafraîchit les documents vus pour la dernière fois il y a plus de `STALE_REFRESH_AFTER_DAYS` (90 jours) et repère ceux qui ont disparu de leur source.

Chaque ligne périmée est réinterrogée par son identifiant natif : trouvée → `raw_data` rafraîchi (re-traité si l'empreinte a changé) et `last_seen_at` repoussé ; absence confirmée → `disappeared_at` posé ; erreur transitoire → laissée, retentée plus tard.

La sélection se borne aux années de la fenêtre courante, lues sur `source_publications.pub_year` — `theses` faisant exception, tout son historique restant éligible. Le seuil étale la charge : une passe ne ramasse que ce qui vient de franchir les 90 jours.

`not_found_at` marque un document que la source n'a jamais rendu ; `disappeared_at`, un document qu'elle rendait et cesse de rendre.

`disappeared_at` est un **marqueur seul** : rien en aval ne l'exploite, ni suppression, ni exclusion, ni propagation.

## Listes d'auteurs tronquées (`fetch_truncated`)

L'[API OpenAlex](../sources/03-openalex.md) plafonne la liste des auteurs à 100 par réponse ; au-delà, les auteurs surnuméraires sont absents du payload moissonné.

Les works concernés sont marqués à l'extraction par le drapeau `staging.authors_truncated` (payload du lot comptant exactement 100 auteurs). Cette phase retélécharge un par un les works marqués et récupère la liste complète des auteurs. Un work qui compte réellement cent auteurs voit son drapeau levé sans réécriture. Le marqueur étant explicite, il survit à la normalisation (qui purge `raw_data`) : un work qui échappe à cette phase — OpenAlex indisponible, budget API épuisé — reste marqué et repris à l'exécution suivante.

Pour que le résultat ne soit pas écrasé par le prochain moissonnage, on met à jour `raw_data` sans toucher à `raw_hash`, qui reste l'empreinte du payload initial : tant que le moissonnage renvoie ce même payload, l'UPSERT laisse `raw_data` en place.
