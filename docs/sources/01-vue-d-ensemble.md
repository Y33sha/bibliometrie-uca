# Vue d'ensemble

*À jour le 2026-09-06.*

Le système intègre 7 sources bibliographiques principales, complétées par des sources d'enrichissement et des imports manuels.

## Sources bibliographiques

| Source | Type | Couverture | API | Credentials |
|--------|------|-----------|-----|-----|
| [HAL](02-hal.md) | Archive ouverte | Publications déposées par les chercheurs UCA | Solr (search) | aucun |
| [OpenAlex](03-openalex.md) | Base bibliométrique ouverte | Vise l'exhaustivité sur le plan mondial | REST (works, sources, publishers) | clé API gratuite, ou *polite pool* via *mailto* |
| [Web of Science](04-wos.md) | Base bibliométrique commerciale | Publications indexées WoS (critères de qualité académique) | REST (Expanded API, quota annuel) | clé API sur demande (selon contrat établissement) |
| [ScanR](05-scanr.md) | Portail officiel du MESR | Publications de l'écosystème français de la recherche | Elasticsearch (DataESR) | login et mot de passe sur demande, par le [formulaire de contact](https://scanr.enseignementsup-recherche.gouv.fr/about/contact) |
| [theses.fr](08-theses.md) | Portail officiel des thèses françaises | Thèses soutenues + en cours, rattachement par PPN d'établissement | REST (data.gouv.fr) | aucun |
| [Crossref](06-crossref.md) | Agence d'enregistrement de DOI | Publications dotées d'un [DOI](../glossaire.md#doi) Crossref. Aussi consulté pour résoudre les préfixes DOI vers leur Member éditeur. | REST (works, prefixes, members) | *polite pool* via *mailto* |
| [DataCite](07-datacite.md) | Agence d'enregistrement de DOI | Publications dotées d'un [DOI](../glossaire.md#doi) DataCite : jeux de données, logiciels, *preprints*, dépôts d'entrepôts (Zenodo, figshare, recherche-data-gouv…). Aussi consulté pour résoudre les préfixes DOI vers leur entrepôt. | REST (dois, prefixes) | *polite pool* via *mailto* |


### Modes d'interrogation

Ce que le projet interroge dans chaque source, indépendamment de ce que l'API offre par ailleurs.

| Source | Moissonnage par affiliation | Recherche par identifiant de document |
|---|---|---|
| HAL | collection HAL + année | hal-id, NNT, DOI |
| OpenAlex | institution (filtre `lineage`) + année | DOI |
| Web of Science | champ OG (Organization) + année | DOI |
| ScanR | identifiant SIREN + année | DOI |
| theses.fr | PPN d'établissement | NNT |
| Crossref | — | DOI |
| DataCite | — | DOI |

Crossref et DataCite ne portent l'affiliation qu'en chaîne libre, sans identifiant d'établissement : le moissonnage par affiliation y serait peu commode. Le troisième mode envisageable, l'interrogation par identifiant de personne (ORCID, idHAL), n'est employé pour aucune source. <!--TODO: à mettre en place?-->

> **Sources envisagées mais pas exploitées actuellement**
>
> * Serveurs de preprint: ArXiv, Pubmed Central...
> * pour améliorer la couverture SHS: Cairn, Persée
> * Sudoc (catalogue partagé de l'ESR)
> * brevets: INPI
> * divers (enrichissement des entités personnes): ORCID, IdRef

### Gestion des affiliations

*A compléter*

- **OpenAlex** et **WoS**: [affiliations](../glossaire.md#affiliation) résolues de manière algorithmique à partir des [adresses](../glossaire.md#adresse) liées aux publications. Beaucoup d'erreurs causées par des similitudes de noms (dans OpenAlex principalement). Mais la donnée-source (*raw affiliation string*) est présente et exploitable. On ignore les affiliations résolues par les sources et **on reconstruit l'affiliation à partir des adresses brutes**. ([Phase `affiliations`](../pipeline/04-affiliations.md) du pipeline.)

- **HAL**: affiliation basée sur celle renseignée dans le compte HAL des auteurs au moment du dépôt (Cf [doc HAL](https://doc.hal.science/depot-fonctionnement-de-l-affiliation-automatique/#)), éventuellement corrigée manuellement par le déposant. Les métadonnées de HAL ne contiennent pas les adresses brutes présentes dans les publications. On récupère donc les affiliations telles qu'elles sont renseignées dans HAL : les noms de structures sont traités fictivement comme des adresses par l'algo de résolution d'affiliation. Les erreurs d'affiliation dans HAL sont détectées *a posteriori* (pages [hal-problems](../guide-utilisateur/01-pages-publiques.md#problèmes-hal)).

<!--TODO: Compléter avec les autres sources-->

### Entités auteurs

Deux cas de figure:

- Dans **OpenAlex** et **WoS**, chaque auteur de chaque publication est identifié par une clé interne dans le référentiel personnes de la base. Ces entités auteurs sont algorithmiques et peu fiables (même personne fréquemment divisée en entités multiples, ou personnes distinctes confondues). L'ORCID rattaché à *l'entité auteur* (`author.orcid` côté OpenAlex, `PreferredORCID` côté WoS) ne prouve pas sa présence dans la publication : le rattachement peut provenir d'un *matching* algorithmique. Signal peu fiable.
    - **Nuance OpenAlex** : en plus de l'ORCID d'entité, OpenAlex expose parfois un `raw_orcid` au **niveau de l'authorship**, issu des métadonnées brutes de la source. On retient `raw_orcid`, on ignore `author.orcid`.
- Les autres sources (**HAL**, **ScanR**, **theses.fr**, **Crossref**, **DataCite**) sont plus conservatrices: pas de tentative d'identification systématique des auteurs. Une même publication peut avoir des auteurs avec ou sans identifiants.
    - **Crossref**: l'identifiant est toujours ORCID.
    - **DataCite**: l'identifiant est toujours ORCID, porté par les `nameIdentifiers` du *creator*.
    - **HAL**: l'identifiant est un `personId` interne à HAL, qui identifie un compte HAL. Y sont parfois joints d'autres identifiants (`idHAL`, `IdRef`, `ORCID`) quand l'auteur les a ajoutés à son profil HAL.
    - **ScanR**, **theses.fr**: lorsque présent, l'identifiant est toujours [IdRef](../glossaire.md#idref) (référentiel personnes de l'ESR).

| Source | Identifiant auteur | Entité stable ? | Identifiants récupérés si présents |
|---|---|---|---|
| HAL avec compte | `hal_person_id` | ✅ | `hal_person_id`, `idhal`, `orcid`, `idref` |
| HAL sans compte | `formId` | ❌ identifie la chaîne de caractères | (aucun) |
| ScanR avec idref | `idref` | ✅ | `idref`, `orcid` |
| ScanR sans idref | rien | ❌ | (aucun) |
| theses.fr avec PPN | `ppn` (= `idref`) | ✅ | `idref` |
| theses.fr sans PPN | rien | ❌ | (aucun) |
| OpenAlex | `openalex_id` | ⚠️ entité algorithmique non fiable | `raw_orcid` (fiable, article-level, retenu) ; `author.orcid` (peu fiable, ignoré) |
| WoS | `daisng_id` | ⚠️ entité algorithmique non fiable | `researcher_id` (l'ORCID de WoS n'est pas moissonné) |
| CrossRef | rien | ❌ | `orcid` (fiable, article-level) |
| DataCite | rien | ❌ | `orcid` (fiable, article-level) |

Les informations d'identification récupérées depuis les sources (forme de nom, identifiants éventuels) sont stockées dans la table `author_identifying_keys`. La résolution / création des personnes se fait dans la [phase `persons`](../pipeline/08-persons.md) du pipeline à partir de ces éléments.

## Sources complémentaires

| Source | Type | Couverture | API | Credentials |
|--------|------|-----------|-----|-----|
| [Unpaywall](09-sources-supplementaires.md#unpaywall) | Enrichissement OA | Statut Open Access par DOI | REST (gratuit, 100k req/jour) | *polite pool* via *mailto* |
| [DOAJ](09-sources-supplementaires.md#doaj) | Annuaire des revues OA certifiées | Métadonnées qualifiées par revue (licence, APC, sujets…), appariées par ISSN | dump CSV | *polite pool* via *mailto* |
| [Extraction RH](10-imports-manuels.md#extraction-rh) | Import manuel | Personnel UCA (noms, départements, rôles) | Fichier CSV | |
| [Données APC](10-imports-manuels.md#données-apc) | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV | |
