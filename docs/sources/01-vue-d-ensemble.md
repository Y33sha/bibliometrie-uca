# Vue d'ensemble

*Document à jour au 2026-05-26.*

Le système intègre 6 sources bibliographiques principales, complétées par des sources d'enrichissement et des imports manuels.

> TODO: Documenter les modes d'interrogation possibles pour chaque source, celles qui sont utilisées ou non et pourquoi (par affiliation, par identifiant personne, par identifiant document)

## Sources bibliographiques

| Source | Type | Couverture | API | Credentials |
|--------|------|-----------|-----|-----|
| [HAL](02-hal.md) | Archive ouverte | Publications déposées par les chercheurs UCA | Solr (search) | aucun |
| [OpenAlex](03-openalex.md) | Base bibliométrique ouverte | Vise l'exhaustivité sur le plan mondial | REST (works, sources, publishers) | clé API gratuite (créer un compte) |
| [Web of Science](04-wos.md) | Base bibliométrique commerciale | Publications indexées WoS (critères de qualité académique) | REST (Expanded API, quota annuel) | clé API sur demande (selon contrat établissement) |
| [ScanR](05-scanr.md) | Portail officiel du MESRE | Publications de l'écosystème français de la recherche | Elasticsearch (DataESR) | login et mot de passe sur demande (TODO: indiquer mail) |
| [theses.fr](07-theses.md) | Portail officiel des thèses françaises | Thèses soutenues + en cours, rattachement par PPN d'établissement | REST (data.gouv.fr) | TODO: documenter |
| [Crossref](06-crossref.md) | Agence d'enregistrement de DOI | Publications dotées d'un [DOI](../glossaire#doi) Crossref. Aussi consulté pour résoudre les préfixes DOI vers leur Member éditeur. | REST (works, prefixes, members) | *polite pool* via *mailto* |


> **Sources envisagées mais pas exploitées actuellement**
>
> * Serveurs de preprint: ArXiv, Pubmed Central...
> * pour les jeux de données: DataCite, Zenodo, recherche-data-gouv...
> * pour améliorer la couverture SHS: Cairn, Persée
> * Sudoc (catalogue partagé de l'ESR)
> * brevets: INPI
> * divers (enrichissement des entités personnes): ORCID, IdRef

### Gestion des affiliations {#sources-affiliations}

*A compléter*

- **OpenAlex** et **WoS**: [affiliations](../glossaire.md#affiliation) résolues de manière algorithmique à partir des [adresses](../glossaire.md#adresse) liées aux publications. Beaucoup d'erreurs causées par des similitudes de noms (dans OpenAlex principalement). Mais la donnée-source (*raw affiliation string*) est présente et exploitable. On ignore les affiliations résolues par les sources et **on reconstruit l'affiliation à partir des adresses brutes**. ([Phase `affiliations`](../pipeline/05-affiliations.md) du pipeline.)

- **HAL**: affiliation basée sur celle renseignée dans le compte HAL des auteurs au moment du dépôt (Cf [doc HAL](https://doc.hal.science/depot-fonctionnement-de-l-affiliation-automatique/#)), éventuellement complétés manuellement par le déposant. Les métadonnées de HAL ne contiennent pas les adresses brutes présentes dans les publications. On récupère donc les affiliations telles qu'elles sont renseignées dans HAL : les noms de structures sont traités fictivement comme des adresses par l'algo de résolution d'affiliation. Les erreurs d'affiliation dans HAL sont détectées *a posteriori* (pages [hal-problems](../guide-utilisateur/01-pages-publiques.md#problemes-hal)).

<!--TODO: Compléter avec les autres sources-->

### Nature des entités auteurs {#entites-auteurs}

Deux cas de figure:

- Dans **OpenAlex** et **WoS**, chaque auteur de chaque publication est identifié par une clé interne dans le référentiel personnes de la base. Ces entités auteurs sont algorithmiques et peu fiables (même personne fréquemment divisée en entités multiples, ou personnes distinctes confondues). L'ORCID rattaché à *l'entité auteur* (`author.orcid` côté OpenAlex, `PreferredORCID` côté WoS) ne prouve pas sa présence dans la publication : le rattachement peut provenir d'un *matching* par nom effectué par la source. Signal peu fiable.
    - **Nuance OpenAlex** : en plus de l'ORCID d'entité, OpenAlex expose un `raw_orcid` au **niveau de l'authorship**, recopié tel quel de la métadonnée brute de la source amont (Crossref pour l'essentiel des articles à éditeur) — déposé par l'auteur, donc fiable au même titre qu'un ORCID Crossref. C'est `raw_orcid` qu'on retient ; `author.orcid` est ignoré. WoS n'a pas d'équivalent (son `PreferredORCID` est l'ORCID algorithmique, ignoré).
- Les autres sources (**HAL**, **ScanR**, **theses.fr**, **Crossref**) sont plus conservatrices: pas de tentative d'identification systématique des auteurs. Une même publication peut avoir des auteurs avec ou sans identifiants.
    - **Crossref**: l'identifiant est toujours ORCID. Présent sur une faible minorité d'*authorships* <!--TODO: chiffrer-->, mais signal excellent car la source est toujours l'auteur (circuit: auteur => éditeur => Crossref).
    - **HAL**: l'identifiant est un `personId` interne à HAL, qui identifie un compte HAL. Y sont parfois joints d'autres identifiants (`idHAL`, `IdRef`, `ORCID`) si l'auteur les a ajoutés à son profil HAL. Signal excellent à condition que le document soit rattaché au bon compte HAL (erreurs d'homonymie possibles sur les publis multi-auteurs avec identification automatisée des auteurs lors du dépôt).
    - **ScanR**, **theses.fr**: lorsque présent, l'identifiant est toujours [IdRef](../glossaire#idref) (référentiel personnes de l'ESR). Source du lien IdRef-publi: pas clair (algorithmique? déclaratif pour les personnes liées aux thèses?) A élucider. Globalement fiable.

| Source | Identifiant auteur | Entité stable ? | Identifiants récupérés si présents |
|---|---|---|---|
| HAL avec compte | `hal_person_id` | ✅ | `hal_person_id`, `idhal`, `orcid`, `idref` |
| HAL sans compte | `formId` | ❌ identifie la chaîne de caractères | (aucun) |
| ScanR avec idref | `idref` | ✅ | `idref`, `orcid` |
| ScanR sans idref | rien | ❌ | (aucun) |
| theses.fr avec PPN | `ppn` (= `idref`) | ✅ | `idref` |
| theses.fr sans PPN | rien | ❌ | (aucun) |
| OpenAlex | `openalex_id` | ⚠️ entité algorithmique non fiable | `raw_orcid` (fiable, article-level, retenu) ; `author.orcid` (peu fiable, ignoré) |
| WoS | `daisng_id` | ⚠️ entité algorithmique non fiable | `orcid` (peu fiable), `researcher_id` |
| CrossRef | rien | ❌ | `orcid` (fiable, article-level) |

Vu l'hétérogénéité des entités personnes selon les sources, il a été décidé de ne pas maintenir de table `source_persons`. Les informations récupérées depuis les sources (forme de nom, identifiants éventuels) sont portées par `source_authorships` (`raw_author_name` pour traçabilité, `author_name_normalized` pour matching par nom, `source_identifiers` JSONB pour les identifiants persistants associés (ORCID, IdRef, idHAL)). La déduplication / création des personnes canoniques se fait dans la [phase `persons`](../pipeline/07-persons.md) du pipeline à partir de ces éléments.

## Sources complémentaires

| Source | Type | Couverture | API | Credentials |
|--------|------|-----------|-----|-----|
| [Unpaywall](08-sources-supplementaires.md#unpaywall) | Enrichissement OA | Statut Open Access par DOI | REST (gratuit, 100k req/jour) | *polite pool* via *mailto* |
| [DOAJ](08-sources-supplementaires.md#doaj) | Annuaire des revues OA certifiées | Métadonnées qualifiées par revue (licence, APC, sujets…), interrogée par ISSN | REST + dump CSV bootstrap | *polite pool* via *mailto* |
| [ROR](08-sources-supplementaires.md#ror) | Registry des organismes de recherche | Typage canonique des éditeurs (`publisher_type`) via le champ `types` du record ROR | REST v2 | *polite pool* via *mailto* |
| [Base RH](09-imports-manuels.md#donnees-rh) | Import manuel | Personnel UCA (noms, départements, rôles) | Fichier CSV | |
| [Données APC](09-imports-manuels.md#donnees-apc) | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV | |
