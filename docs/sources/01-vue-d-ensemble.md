# Vue d'ensemble

*À jour le 2026-09-10.*

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

### Une même publication vue par chaque source

Exemple d'une publication vue à travers différentes sources.

 Titre : *Mixed data k-Anonymization by Consistent Maximal Association and Microaggregation*. DOI : [10.1145/3746252.3761293](https://doi.org/10.1145/3746252.3761293). Les proportions citées portent sur les 58 608 publications du périmètre présentes dans au moins deux sources.

#### Publication

| Source | Titre |
|---|---|
| Crossref | `Mixed data <i>k</i> -Anonymization by Consistent Maximal Association and Microaggregation` |
| ScanR | `Mixed data <i>k</i> -Anonymization by Consistent Maximal Association and Microaggregation` |
| HAL | `Mixed data k -Anonymization by Consistent Maximal Association and Microaggregation` |
| OpenAlex | `Mixed data k -Anonymization by Consistent Maximal Association and Microaggregation` |
| Web of Science | `Mixed data k-Anonymization by Consistent Maximal Association and Microaggregation` |

Les sources donnent le même titre dans 89,7 % des cas. Ici, l'éditeur a mis le *k* en italique. Crossref transmet la balise, ainsi que les retours à la ligne et l'indentation du fichier source ; ScanR reprend Crossref à l'identique. HAL et OpenAlex portent le titre sans balise, avec l'espace que son retrait laisse devant le tiret. Web of Science donne la seule chaîne propre.

| Source | Année | Type | Langue | DOI | Résumé |
|---|---|---|---|---|---|
| Crossref | 2025 | `conference_paper` | absente | présent | absent |
| HAL | 2025 | `conference_paper` | `en` | présent | absent |
| OpenAlex | 2025 | `conference_paper` | `en` | présent | 1 083 caractères |
| ScanR | 2025 | `conference_paper` | absente | présent | absent |
| Web of Science | 2025 | `conference_paper` | `English` | présent | 1 084 caractères |

**Année.** Les sources s'accordent dans 88,6 % des cas. Quand elles divergent, l'écart est d'une seule année quatre fois sur cinq. Les deux dates en cause sont la mise en ligne et la parution.

**Type de document.** Le champ le plus divergent : 60,7 % d'accord. Chaque source a sa nomenclature — `proceedings-article` pour Crossref, `COMM` pour HAL, `conference-paper` pour OpenAlex, `proceedings` pour ScanR, `Proceedings Paper` pour Web of Science. La phase `metadata_correction` les ramène toutes à un vocabulaire commun, ici `conference_paper`.

**Langue.** Trois sources sur cinq la renseignent, dans deux formats.

**DOI.** Les sources s'accordent toujours sur le DOI quand elles le portent. Dans 48,6 % des cas, au moins une source l'omet.

#### Revue

| Source | Valeur |
|---|---|
| HAL | `CIKM '25: The 34th ACM International Conference on Information and Knowledge Management`, sans rattachement à une entrée de revue |
| Crossref | `Proceedings of the 34th ACM International Conference on Information and Knowledge Management` |
| ScanR | même entrée que Crossref |
| Web of Science | `PROCEEDINGS OF THE 34TH ACM INTERNATIONAL CONFERENCE ON INFORMATION AND KNOWLEDGE MANAGEMENT, CIKM 2025` |
| OpenAlex | absente |

Ces actes n'ont pas d'ISSN. Le rapprochement se fait alors sur le titre normalisé, qui passe en minuscules et retire la ponctuation : la casse et les apostrophes sont sans effet. Web of Science ajoute au titre du volume le sigle de la conférence et son année, ce qui suffit à produire une clé différente. Deux entrées coexistent donc pour un même volume, l'une typée `proceedings`, l'autre `journal`. 5,4 % des publications sont rattachées à plus d'une revue.

#### Éditeur

| Source | Valeur |
|---|---|
| Crossref, ScanR | `Association for Computing Machinery (ACM)`, typé `learned_society` |
| Web of Science | `ASSOC COMPUTING MACHINERY`, typé `unknown` |

Les éditeurs se rapprochent par identifiant OpenAlex, puis par nom normalisé. Web of Science abrège `Association` en `Assoc` et omet le sigle : le nom normalisé diffère, et un second éditeur naît, sans le type porté par le premier.

#### Sujets

| Source | Valeur |
|---|---|
| Crossref | aucun |
| HAL | domaine `Statistiques [stat]/Machine Learning [stat.ML]` |
| OpenAlex | `Privacy-Preserving Technologies in Data` (0,993), `Cryptography and Data Security` (0,001), `Privacy, Security, and Data Protection` (0,001) |
| ScanR | `Privacy-Preserving Technologies in Data` (0,916), `Data Quality and Management` (0,037), `Machine Learning and Data Classification` (0,005) |
| Web of Science | mots-clés d'auteur `Data privacy`, `Mixed-type data`, `k-anonymization`, `Microaggregation` ; catégories `Computer Science, Artificial Intelligence`, `Computer Science, Information Systems`, `Computer Science, Theory & Methods` |

Chaque source procède différemment. HAL porte les domaines choisis par le déposant, qui n'a saisi aucun mot-clé libre ici. Web of Science porte les mots-clés fournis par les auteurs, plus ses propres catégories disciplinaires. OpenAlex calcule des topics et leur attribue un score. ScanR redistribue les topics d'OpenAlex : les identifiants sont ceux d'OpenAlex, la liste et les scores viennent d'un instantané différent.

#### Auteurs

| Source | Forme du nom | Identifiants du premier auteur | Identifiants du second auteur |
|---|---|---|---|
| Crossref | `Julien Ah-Pine` | ORCID `0000-0001-6898-3961` | ORCID `0009-0004-4535-8644` |
| HAL | `Julien Ah-Pine` | idHAL `julien-ah-pine`, ORCID `0000-0001-6898-3961`, compte HAL `15506` | ORCID `0009-0004-4535-8644`, compte HAL `1623465` |
| OpenAlex | `Julien Ah-Pine` | ORCID `0000-0001-6898-3961` | ORCID `0009-0004-4535-8644` |
| ScanR | `Julien Ah-Pine` | IdRef `139791140`, ORCID `0000-0001-6898-3961` | IdRef `253123445`, ORCID `0000-0002-4302-1878` |
| Web of Science | `Ah-Pine, Julien` | ResearcherID `PQT-5225-2026` | ResearcherID `DUU-4326-2022` |

Web of Science inverse le nom et le prénom ; les autres sources donnent la forme directe. Ces formes et ces identifiants alimentent `author_identifying_keys`. La [phase `persons`](../pipeline/08-persons.md) crée ou retrouve les personnes à partir de cette table.

Le second auteur porte deux ORCID différents. Une seule des deux valeurs peut être exacte : ScanR ou les trois autres sources rattachent le mauvais identifiant.

Part des mentions d'auteur portant au moins un identifiant : Web of Science 100 %, theses.fr 87,2 %, ScanR 43,8 %, Crossref 43,7 %, OpenAlex 33,2 %, DataCite 11,9 %, HAL 5,1 %. Le décompte porte sur toutes les mentions, co-auteurs extérieurs compris. Les publications à plusieurs centaines d'auteurs pèsent donc fortement sur ces proportions.

#### Adresses et structures

| Source | Adresses du premier auteur |
|---|---|
| Crossref | `Université Clermont Auvergne, Clermont Auvergne INP, CNRS, Mines Saint-Etienne, SIGMA Clermont, LIMOS, Clermont-Ferrand, France` |
| OpenAlex | même chaîne que Crossref |
| Web of Science | `Univ Clermont Auvergne, Clermont Auvergne INP, CNRS, Mines St Etienne,SIGMA Clermont,LIMOS, Clermont Ferrand, France` |
| HAL | `Centre d'Études et de Recherches sur le Développement International`, `Centre National de la Recherche Scientifique`, `École des Mines de Saint-Étienne`, `Institut de Recherche pour le Développement`, `Institut Mines-Télécom [Paris]`, `Institut national polytechnique Clermont Auvergne`, `Laboratoire d'Informatique, de Modélisation et d'Optimisation des Systèmes`, `Université Clermont Auvergne` |
| ScanR | aucune |

Crossref, OpenAlex et Web of Science portent l'adresse imprimée dans l'article, entière ou abrégée. Les trois donnent les mêmes cinq structures : l'université, l'école d'ingénieurs, le CNRS, l'école des mines et le laboratoire. HAL porte les structures rattachées au compte de l'auteur : deux d'entre elles, le centre de recherche sur le développement international et l'institut de recherche pour le développement, sont sans rapport avec cet article. ScanR donne les auteurs sans adresse pour cette publication.

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
