# Moissonnage

*À jour le 2026-10-28.*

Récupère les données brutes depuis les API et les stocke en JSONB dans le *staging*.

## Moissonnage par affiliation (`harvest`)

**Critères de requête**:
- **années** de publication : de l'année de début à l'année courante. L'année de début est l'argument `--start-year`, à défaut la valeur [configurable](../guide-utilisateur/administration/04-workflow.md#années) dans `admin/config`. Une thèse soutenue suit la fenêtre par son année de soutenance ; une thèse en cours est toujours retenue ;
- **affiliation** des publications ([périmètre configurable](../guide-utilisateur/administration/04-workflow.md#périmètres) dans `admin/config`). Il s'agit des affiliations *telles qu'elles sont renseignées dans chaque source*. Elles peuvent varier d'une source à l'autre et être incomplètes ou erronées. DataCite, dont les affiliations sont du texte libre, s'interroge par mots-clés saisis pour chaque structure.

En mode `daily`, seul HAL est moissonné : les dépôts de la même plage d'années, modifiés depuis le dernier moissonnage quotidien réussi, ou depuis 30 jours à défaut.

**Gestion des changements**:
- Le moissonnage calcule l'empreinte de chaque payload, sans ses champs volatils. Un document dont l'empreinte change est normalisé de nouveau.
- `last_seen_at` est repoussée chaque fois qu'un document est revu.

## Moissonnage par personne (`harvest_by_person`)

Une publication dont les auteurs signent sans affiliation au périmètre échappe au moissonnage par affiliation. Cette phase, jouée en mode `full`, interroge chaque source sur les identifiants des personnes RH, confirmés ou authentifiés, sur la même plage d'années.

- **Identifiants par source** : ORCID dans HAL, OpenAlex, ScanR, Crossref et DataCite ; idHAL dans HAL ; IdRef dans HAL et ScanR (profil de chaque source, `domain/sources/registry.py`).
- **Lots de personnes** : une requête réunit tous les identifiants d'un lot de personnes. Un document que plusieurs lots ramènent est écrit une fois.
- **Provenance** : les lignes créées ont le mode d'entrée `person_identifier`.

## Documents absents d'une source (`fetch_missing`)

Le moissonnage interroge les sources sur le critère de l'affiliation : un document peut être présent dans une source et ne pas être trouvé par moissonnage, si l'affiliation n'y est pas correctement renseignée. On cherche donc dans chaque source les documents trouvés seulement dans les autres.

**`fetch_missing.hal_by_id` et `fetch_missing.scanr_by_hal_id` : documents manquants, par hal-id.**
Dans HAL, les documents dont le hal-id figure dans OpenAlex ou ScanR et qui sont absents de `staging`. Dans ScanR, les documents dont le hal-id figure dans HAL ou OpenAlex et qu'aucun enregistrement source ScanR ne contient.

**`fetch_missing.hal_by_nnt` et `fetch_missing.theses_by_nnt` : thèses manquantes, par NNT.**
Dans HAL, en mode full, les thèses de theses.fr sans document HAL. Dans theses.fr, les thèses dont le NNT figure dans une autre source et qui sont absentes de theses.fr dans `staging`, par exemple une thèse soutenue dans un autre établissement.

**`fetch_missing.doi.<source>` : DOI manquants par source.**
Pour chacune des six sources interrogeables par DOI — HAL, OpenAlex, WoS, ScanR, Crossref, DataCite —, recherche les documents présents dans les autres sources et non trouvés dans celle-ci par le moissonnage initial. Les DOI cherchés sont ceux des publications de la fenêtre d'années du run : l'un des enregistrements sources de la publication a son année dans la fenêtre. Crossref, non interrogeable par affiliation, est seulement interrogé ici et par personne.

Crossref et DataCite reçoivent seulement les DOI dont le préfixe est enregistré chez eux, d'après l'agence que la phase [resolve_ra](05-publishing.md#agences-denregistrement-doi-resolve_ra) a résolue. Un DOI dont le préfixe est sans agence attend le run suivant.

**Recherches infructueuses.** Chaque identifiant cherché en vain est inscrit dans `failed_lookups`. L'échec est définitif auprès du registre qui attribue l'identifiant (HAL pour un hal-id, theses.fr pour un NNT, doi.org pour un DOI). Ailleurs, l'identifiant est cherché de nouveau après le délai `fetch_missing_retry_after_days`. La phase `metadata_correction` retire les DOI inconnus de doi.org et les hal-id introuvables dans HAL.

## Documents périmés et disparus (`fetch_stale`)

Jouée en mode `full`, après `fetch_missing`, cette phase rafraîchit les documents vus pour la dernière fois il y a plus que le délai `fetch_stale_after_days` (90 jours par défaut, réglable dans `admin/config`) et repère ceux qui ont disparu de leur source.

Chaque ligne périmée est réinterrogée par son identifiant natif :
- trouvée → `raw_data` rafraîchi et `last_seen_at` repoussé ;
- absence confirmée → `disappeared_at` posé ;
- erreur transitoire → laissée, retentée plus tard.

La sélection se borne aux années de la fenêtre courante, lues sur `source_records.publication_year`. Une thèse en cours, qui n'a pas d'année de soutenance, est relue quelle que soit la fenêtre.

## Listes d'auteurs tronquées (`fetch_truncated`)

L'[API OpenAlex](../sources/03-openalex.md) plafonne la liste des auteurs à 100 par réponse ; au-delà, les auteurs surnuméraires sont absents du payload moissonné.

Le moissonnage et la recherche par DOI de `fetch_missing` marquent `staging.authors_truncated` sur les documents de 100 auteurs. Cette phase retélécharge un par un les documents marqués, récupère la liste complète des auteurs et retire la marque. Un document absent d'OpenAlex perd aussi sa marque. Quand OpenAlex est indisponible, la marque reste et le document est repris au run suivant.
