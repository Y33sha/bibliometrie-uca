# Vue d'ensemble

*Document à jour au 2026-05-11.*

Le système intègre 6 sources bibliographiques principales, complétées par des imports manuels et des APIs d'enrichissement.

> TODO: Documenter les modes d'interrogation possibles pour chaque source, celles qui sont utilisées ou non et pourquoi (par affiliation, par identifiant personne, par identifiant document)

| Source | Type | Couverture | API | Credentials |
|--------|------|-----------|-----|-----|
| HAL | Archive ouverte | Publications déposées par les chercheurs UCA | Solr (search) | aucun |
| OpenAlex | Base bibliométrique ouverte | Vise l'exhaustivité sur le plan mondial | REST (works, sources) | clé API gratuite (créer un compte) |
| Web of Science | Base bibliométrique commerciale | Publications indexées WoS (critères de qualité académique) | REST (Expanded API, quota annuel) | clé API sur demande (selon contrat établissement) |
| ScanR | Portail officiel du MESRE | Publications de l'écosystème français de la recherche | Elasticsearch (DataESR) | login et mot de passe sur demande (TODO: indiquer mail) |
| theses.fr | Portail officiel des thèses françaises | Thèses soutenues + en cours, rattachement par PPN d'établissement | REST (data.gouv.fr) | TODO: documenter |
| [Crossref](../glossaire#crossref) | Agence d'enregistrement de DOI | Publications dotées d'un [DOI](../glossaire#doi) Crossref | REST (works) | *polite pool* via *mailto* |
| Unpaywall | Enrichissement OA | Statut Open Access par DOI | REST (gratuit, 100k req/jour) | *polite pool* via *mailto* |
| Base RH | Import manuel | Personnel UCA (noms, départements, rôles) | Fichier CSV | |
| Données [APC](../glossaire#apc) | Import manuel | Paiements APC (montants, éditeurs) | Fichier CSV | |

> **Sources envisagées mais pas exploitées actuellement**
>
> * Serveurs de preprint: ArXiv, Pubmed Central...
> * pour les jeux de données: DataCite, Zenodo, recherche-data-gouv...
> * pour améliorer la couverture SHS: Cairn, Persée
> * Sudoc (catalogue partagé de l'ESR)
> * brevets: INPI
> * divers (enrichissement des entités personnes, revues): ORCID, IdRef, DOAJ

## Gestion des affiliations {#sources-affiliations}

*A compléter*

- **OpenAlex** et **WoS**: [affiliations](../glossaire.md#affiliation) résolues de manière algorithmique à partir des [adresses](../glossaire.md#adresse) liées aux publications. Beaucoup d'erreurs causées par des similitudes de noms (dans OpenAlex principalement). Mais la donnée-source (*raw affiliation string*) est présente et exploitable. On ignore les affiliations résolues par les sources et **on reconstruit l'affiliation à partir des adresses brutes**. ([Phase `affiliations`](../pipeline/04-affiliations.md) du pipeline.)

- **HAL**: affiliation basée sur celle renseignée dans le compte HAL des auteurs au moment du dépôt (Cf [doc HAL](https://doc.hal.science/depot-fonctionnement-de-l-affiliation-automatique/#)), éventuellement complétés manuellement par le déposant. Les métadonnées de HAL ne contiennent pas les adresses brutes présentes dans les publications. On récupère donc les affiliations telles qu'elles sont renseignées dans HAL : les noms de structures sont traités fictivement comme des adresses par l'algo de résolution d'affiliation. Les erreurs d'affiliation dans HAL sont détectées *a posteriori* (pages [hal-problems](../guide-utilisateur/01-pages-publiques.md#problemes-hal)).

<!--TODO: Compléter avec les autres sources-->

## Nature des entités auteurs {#entites-auteurs}

Deux cas de figure:

- Dans **OpenAlex** et **WoS**, chaque auteur de chaque publication est identifié par une clé interne dans le référentiel personnes de la base. Ces entités auteurs sont algorithmiques et peu fiables (même personne fréquemment divisée en entités multiples, ou personnes distinctes confondues). La présence d'un identifiant ORCID sur ces sources ne prouve pas sa présence dans la publication: le rattachement peut provenir d'un *matching* par nom effectué par OpenAlex/WOS. Signal peu fiable.
- Les autres sources (**HAL**, **ScanR**, **theses.fr**, **Crossref**) sont plus conservatrices: pas de tentative d'identification systématique des auteurs. Une même publication peut avoir des auteurs avec ou sans identifiants.
    - **Crossref**: l'identifiant est toujours ORCID. Présent sur une faible minorité d'*authorships* <!--TODO: chiffrer-->, mais signal excellent car la source est toujours l'auteur (circuit: auteur => éditeur => Crossref).
    - **HAL**: l'identifiant est un `personId` interne à HAL, qui identifie un compte HAL. Y sont parfois joints d'autres identifiants (`idHAL`, `IdRef`, `ORCID`) si l'auteur les a ajoutés à son profil HAL. Signal excellent à condition que le document soit rattaché au bon compte HAL (erreurs d'homonymie possibles sur les publis multi-auteurs avec identification automatisée des auteurs).
    - **ScanR**, **theses.fr**: lorsque présent, l'identifiant est toujours [IdRef](../glossaire#idref) (référentiel personnes de l'ESR). Source du lien IdRef-publi: pas clair (algorithmique? déclaratif pour les personnes liées aux thèses?) A élucider. Globalement fiable.

| Source | Identifiant auteur | Entité stable ? | Identifiants récupérés si présents |
|---|---|---|---|
| HAL avec compte | `hal_person_id` | ✅ | `hal_person_id`, `idhal`, `orcid`, `idref` |
| HAL sans compte | `formId` | ❌ identifie la chaîne de caractères | (aucun) |
| ScanR avec idref | `idref` | ✅ | `idref`, `orcid` |
| ScanR sans idref | rien | ❌ | (aucun) |
| theses.fr avec PPN | `ppn` (= `idref`) | ✅ | `idref` |
| theses.fr sans PPN | rien | ❌ | (aucun) |
| OpenAlex | `openalex_id` | ⚠️ entité algorithmique non fiable | `orcid` (peu fiable) |
| WoS | `daisng_id` | ⚠️ entité algorithmique non fiable | `orcid` (peu fiable), `researcher_id` |
| CrossRef | rien | ❌ | `orcid` (fiable, article-level) |

Vu l'hétérogénéité des entités personnes selon les sources, il a été décidé de ne pas maintenir de table `source_persons`. Les informations récupérées depuis les sources (forme de nom, identifiants éventuels) sont portées par `source_authorships` (`raw_author_name` pour traçabilité, `author_name_normalized` pour matching par nom, `source_identifiers` JSONB pour les identifiants persistants associés (ORCID, IdRef, idHAL)). La déduplication / création des personnes canoniques se fait dans la [phase `persons`](../pipeline/06-persons.md) du pipeline à partir de ces éléments.
