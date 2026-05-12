# Pipeline de traitement — Bibliométrie UCA

Ce fichier présente la logique du pipeline de traitement. Pour les modalités d'exécution, voir [Guide d'exploitation](exploitation#pipeline).

## Vue d'ensemble

Le peuplement de la base s'effectue via un *pipeline* composé des étapes suivantes:

### Moissonnage
- [Moissonnage](#extract): Récupère les données brutes depuis les API et les stocke en JSONB dans la table de *staging*.
- [Fetch missing HAL id](#fetch_missing_hal_id): Récupère depuis HAL les documents référencés par d'autres sources mais absents de notre staging HAL.
- [Fetch missing DOI](#fetch_missing_doi): Recherche ciblée par DOI dans chaque source des records manquants.
### Normalisation
- [Normalisation](#normalize): Transforme les données brutes (*staging*) en tables structurées *par source*: `*_publications`, `*_authors`, `*_authorships`, `*_structures`.
### Repérage des affiliations
- [Adresses](#addresses): Peuple la table `addresses` à partir des adresses brutes associées aux [authorships](glossaire#authorship). Résout les affiliations des adresses à l'aide des formes de noms associées aux structures canoniques.
- [Affiliations](#affiliations): Renseigne le bool `in_perimeter` et les `structure_ids` des authorships sources.
### Création/rattachement des publications
- Publications: Peuple la table canonique `publications`  à partir des publications sources *via* les authorhips souces ayant `in_perimeter` = true. Dédoublonne.
### Création/rattachement des personnes
- [Personnes](#creation-personnes): Peuple la table canonique `persons` et ses tables satellites `person_name_forms` et `person_identifiers` (ORCID, idHAL, IdRef) *via* les authorhips souces ayant `in_perimeter` = true. Mappe les authorships sources aux `person_id` créées.
- [Authorships](#authorships): Peuple la table canonique `authorships` (liens entre `publications` canoniques et `persons` canoniques) à partir des `person_id` référencés dans les authorships sources.
### Enrichissements divers
- [Pays](#countries): détection automatisée des pays des adresses. Utile pour interroger les collaborations internationales.
- [Statut open access](#enrich): interrogation de l'API Unpaywall pour obtenir le statut *open access* le plus à jour

## Phases détaillées

### <span id="extract"></span>Phase 1 — `extract` : Moissonnage

Récupère les données brutes depuis les API et les stocke en JSONB dans le *staging*.

```mermaid
flowchart LR
    A[API HAL]-->|extract_hal|B[staging]
    C[API OpenAlex]-->|extract_openalex|B
    E[API WOS]-->|extract_wos|B
    G[API ScanR]-->|extract_scanr|B
    H[API theses.fr]-->|extract_theses|B
    classDef new  fill:#bbf
    class B new;
```

**Critères de requête**:
- **années** de publication (configurables dans admin/config : *weekly* couvre les années n et n-1, *full* fait une repasse complète sur les années n-5 à n);
- **affiliation** des publications (UCA, CHU, INP). Il s'agit des affiliations *telles qu'elles sont renseignées dans chaque source*. Elles peuvent varier d'une source à l'autre et être incomplètes ou erronées. Ce point est géré dans les étapes ultérieures.

**Gestion des changements**:
- Chaque *record* est hashé (MD5) pour détecter les changements lors des réexécutions. Une publication dont les métadonnées ont changé sera ré-importée et re-traitée.
- Même sans changement, la colonne `last_seen_at` documente la dernière date où une publication a été détectée par le script d'import. En cas de disparition d'une publication dans les sources (par ex. dédoublonnage dans HAL), cette colonne permettra de détecter les suppressions et de nettoyer la base. Rien n'est en place pour l'instant.
<!-- TODO: Mettre en place le process pour détecter les publications disparues et les nettoyer de la base (ou les archiver?). -->

**Cas particulier**:

L'API OpenAlex limite les authorships à 100 par publication dans les requêtes *bulk*. Un *refetch* individuel des publications avec 100 authorships est nécessaire.

**`refetch_truncated.py`** — re-télécharge un par un les works OpenAlex tronqués à 100 auteurs.
Pour éviter d'écraser ces publications lors de l'import suivant, un *hash* est calculé en faisant abstraction des authorships.
<!-- TODO: Tester que le meta_hash fonctionne effectivement et que les publis de >100 auteurs ne sont pas écrasées au réimport. -->

### <span id="fetch_missing_hal_id"></span>Phase 2a — `fetch_missing_hal_id` : HAL ids manquants

**`interfaces/cli/pipeline/fetch_missing_hal_id.py`** — télécharge depuis HAL les documents référencés (par hal-id ou NNT) dans d'autres sources mais absents de notre staging HAL. Auto-borné, tourne dans tous les modes.

### <span id="fetch_missing_doi"></span>Phase 2b — `fetch_missing_doi` : DOI manquants par source

**`interfaces/cli/pipeline/fetch_missing_doi.py`** — dispatcher unique qui, pour chaque source cible (OpenAlex, HAL, WoS, ScanR), recherche par DOI les records trouvés dans les autres sources mais absents de celle-ci. La plupart sont effectivement absents ; certains sont repêchés (cause : affiliations différentes selon source). Adapter par source dans `infrastructure/sources/<source>/fetch_missing_doi.py`. Exécuté en mode `full` uniquement (scope policy).

### <span id="normalize"></span>Phase 3 — `normalize` : Normalisation

Transforme les données brutes (staging) en tables structurées par source.

```mermaid
flowchart LR
    A[API HAL]-->B[staging]-->|normalize_hal|G@{ shape: processes, label: "Tables sources:
    source_publications, source_authorships" }
    C[API OpenAlex]-->B-->|normalize_openalex|G
    E[API WOS]-->B-->|normalize_wos|G
    K[API ScanR]-->B-->|normalize_scanr|G
    L[API theses.fr]-->B-->|normalize_theses|G
    M[API CrossRef]-->B-->|normalize_crossref|G
    classDef new  fill:#bbf
    class G new;
```

### <span id="addresses"></span>Phase 4 — `addresses` : Adresses et affiliations

Cette étape extrait les adresses brutes des *authorships* sources et les relie aux structures. Pas d'adresses brutes dans HAL => on utilise la chaîne de caractères du nom de la structure, et on la traite fictivement comme une adresse.
> **TODO:** filtrage à mettre en place côté UI pour ne pas afficher les pseudo-adresses de source HAL dans les onglets "adresses"

```mermaid
flowchart LR
    A[source_authorships]-->|populate_addresses|B[addresses]
    D[structures]-->E[structure_name_forms]
    E-->|resolve_addresses|F[address_structures]
    B-->|resolve_addresses|F
    classDef new  fill:#bbf
    classDef valid  fill:#af5
    class B,F new;
    class D,E valid;
```

1. **`populate_addresses.py`** — split les `raw_affiliation` (séparateur ` | `) en adresses individuelles, déduplique dans la table `addresses`, crée les liens `*_authorship_addresses`
2. **`resolve_addresses.py`** — matche les adresses normalisées avec les formes de nom des structures (`structure_name_forms`). Résultat dans `address_structures`

> **TODO:** documenter la logique de resolve_addresses

### <span id="affiliations"></span>Phase 5 — `affiliations` : Propagation des affiliations

Script : `processing/populate_affiliations.py`

```mermaid
flowchart LR
    A[structures]-->B[address_structures]
    B-->C
    C[addresses]-->|populate_affiliations|D[source_authorships]
    classDef new  fill:#bbf
    classDef valid  fill:#af5
    class D new;
    class A valid;
```

Calcule `in_perimeter` et `structure_ids` sur les authorships des 4 sources.

Deux périmètres :
- **Restreint** (UCA + labos UCA) → détermine `in_perimeter` (bool)
- **Large** (restreint + CHU, INP…) → détermine `structure_ids`

Périmètre centralisé dans `utils/uca_perimeter.py`.


### <span id="publications"></span>Phase 6 — `publications` : Peuplement de la table Publications

```mermaid
flowchart LR
    A[source_publications]-->B[publications]
    classDef new  fill:#bbf
    class B new;
```


Les publications sources sont mappées aux publications canoniques:
- par **DOI** (même DOI = même publi, sauf cas particuliers).
- par **NNT** (numéro national de thèse)
- par **hal-id** (un document OpenAlex ou ScanR qui référence un document HAL)

Les cas douteux (métadonnées identiques ou similaires) sont préservés et sont fusionnés manuellement via la page admin/duplicates.

> **Evolutions envisagées**
> - Ajouter de nouveaux identifiants pouvant servir de clé de déduplication: pmid (Pubmed)...
> - Affiner la détection de DOI faussement distincts référençant le même document (DOI versionnés, concept DOI...)
> - Développer un algorithme de déduplication par identité de métadonnées. Piégeux: beaucoup de cas limites ou difficiles. Logique à soigner.


### <span id="persons"></span>Phase 7 — `persons` : Rattachement et création de personnes

```mermaid
flowchart LR
    A[source_authorships]-->B[persons]
    classDef new  fill:#bbf
    class B new;
```

**`create_persons_from_source_authorships.py`** — algorithme en 3 étapes :

> **Etape initiale à ajouter** : matching par ORCID attesté dans les métadonnées Crossref (= source auteur garantie => meilleur critère possible)

1. **Même nom + même publication + même position auteur** : pour chaque authorship sans `person_id`, cherche sur la même publication (même position) une *authorship* d'une **autre source** déjà rattachée à une personne. Si le nom est compatible → rattacher. Approche conservatrice (requiert position identique dans la liste des auteurs. TODO: voir si cette condition peut être assouplie sans perte de qualité).

> **Limité aux publis de 50 auteurs max**: les méga-papers (plusieurs centaines voire milliers d'auteurs) contiennent souvent des homonymes + l'initiale au lieu du prénom + de fréquents désalignements de position auteur entre sources, pouvant conduire à de faux rattachemements.

2. **Identifiant Idref/ORCID connu** : si l'authorship est liée à un ORCID ou un IdRef déjà présent en base (table `person_identifiers`, avec `status ≠ rejected`) → rattacher. Priorité aux IdRef. Les ORCID/IdRef sont lus depuis `source_authorships.identifiers`.

> Les ORCID provenant de métadonnées OpenAlex ou WoS sont souvent douteux. Ils sont liés à l'entité du référentiel personnes propre à chaque base, mais ces entités sont peu fiables. L'ORCID est généralement absent de la publication: c'est donc un matching algorithmique qui a permis d'associer tel ORCID à tel auteur d'une publi. Étudier la pertinence de conserver cette étape du matching.

3. **Recherche par nom** : lookup par nom normalisé dans `person_name_forms`.
   - Nom mappé à 1 personne → rattacher
   - Nom mappé à >1 personnes → laisser orphelin (pour traitement manuel via `admin/orphan-authorships`)
   - **Nom inconnu → créer nouvelle personne**

**`populate_person_name_forms.py`** — recalcule les formes de nom depuis les sources (persons, HAL, OpenAlex, WoS, ScanR, theses, CrossRef).
- Lors de la création d'une personne (ou d'une correction manuelle du nom/prénom): génération automatique des variantes normalisées "prénom nom", "nom prénom", "initiales nom", "nom initiales".
- Lors d'un rattachement d'authorship: les formes de nom liées sont ajoutées aux name_forms de cette personne.

Fonctions de compatibilité de noms dans `utils/names.py`.

**Notes sur `source_persons`** (cf. [chantier source_persons](chantiers/2026-04-28_source-persons.md)) :
- La table héberge uniquement les entités auteurs avec un identifiant stable côté source (HAL+`hal_person_id`, ScanR+idref, theses+PPN).
- Pour les sources sans identifiant stable (OA, WoS, CrossRef, et les comptes HAL non identifiés / ScanR sans idref / theses sans PPN), `source_authorships.source_person_id` reste NULL et les identifiants normalisés vivent sur `source_authorships.identifiers` (JSONB).


### <span id="authorships"></span>Phase 8 — `authorships` : Construction des authorships canoniques

```mermaid
flowchart LR
    F[source_authorships]---E
    E[source_publications]---A
    F---C
    F---D
    A[publications]---B[authorships]
    C[persons]---B
    B---D[structures]
    classDef new  fill:#bbf
    class B new;
```

**`build_authorships.py`** construit la table `authorships` en 4 étapes :

1. **Insertion** des paires (publication_id, person_id) manquantes, depuis les `source_authorships` non exclues (toutes sources : HAL, OpenAlex, WoS, ScanR, theses, CrossRef)
2. **FK** : rattache chaque `source_authorships` à son authorship canonique via `source_authorships.authorship_id`
3. **Métadonnées** : propage `author_position` et `is_corresponding` selon `SOURCE_PRIORITY` (theses > CrossRef > ScanR > HAL > OpenAlex > WoS)
4. **UCA** : propage `in_perimeter` et `structure_ids` depuis toutes les sources (union, déjà calculées par `populate_affiliations.py`)

Les authorships sources marquées `excluded = TRUE` sont ignorées à toutes les étapes. Les publications de type `peer_review` sont exclues de la propagation UCA.


### <span id="countries"></span>Phase 9 — `countries` : Pays des publications

Trois scripts enchaînés :

1. **`interfaces/cli/detect_address_countries.py`** : détection automatique du pays des adresses sans pays. Parse le dernier segment après la dernière virgule et le matche contre la table `country_name_forms` (276 formes, 140 pays, variantes anglais/français/codes ISO/abréviations WoS). Rapide et fiable.

2. **`interfaces/cli/suggest_address_countries.py`** : pour les adresses restantes (pays absent du dernier segment), cherche une adresse similaire avec pays connu via LIKE sur le texte normalisé. Plus lent, résultats stockés dans `suggested_countries` (validation manuelle via l'interface admin).

3. **`interfaces/cli/pipeline/refresh_publication_countries.py`** : recalcule `publications.countries` en faisant l'union des pays des 4 sources (HAL via structures, OpenAlex/WoS/ScanR via adresses résolues).

### <span id="enrich"></span>Phase 10 — `enrich` : Enrichissements optionnels

Exécutée uniquement en mode `full` :

| Script | Rôle |
|--------|------|
| `interfaces/cli/pipeline/enrich_oa_status.py` | Statut *open access* via API [Unpaywall](glossaire#unpaywall) => souvent plus à jour que le statut renseigné dans les sources |
| `interfaces/cli/pipeline/enrich_journal_apc.py` | Montant APC par revue via API OpenAlex Sources => **ne sert à rien pour l'instant**, voir si on garde ou pas |

## Résumé: <span id='tables-canoniques'></span>Peuplement des tables canoniques


1. Les **structures** préexistent au pipeline.

```mermaid
flowchart LR
    subgraph vérité
    direction LR
    A[publications]-.-B[authorships]
    C[persons]-.-B
    B-.-F[structures]
    end
    classDef valid  fill:#af5
    class F valid;
```

2. La [phase 3](#normalize) (`normalize`) peuple la table **publications** par mapping à partir des publications sources.

```mermaid
flowchart LR
    source_publications-->A

    subgraph vérité
    direction LR
    A[publications]-.-B[authorships]
    C[persons]-.-B
    B-.-F[structures]
    end
    classDef valid  fill:#af5
    class F,A valid;
```

3. Après repérage des affiliations dans les authorships sources, la [phase 7](#creation-personnes) `persons` crée les **personnes** correspondant aux *authorships* UCA (ou les rattache aux personnes existantes).

```mermaid
flowchart LR
    source_publications-->A
    source_authorships---source_publications
    source_authorships-->C

    subgraph vérité
    direction LR
    A[publications]-.-B[authorships]
    C[persons]-.-B
    B-.-F[structures]
    end
    classDef valid  fill:#af5
    class F,A,C valid;
```

4. Les **authorships** canoniques sont déduites à partir des sources dans la [phase 8](#authorships) (`authorships`). L'information (`person_id`, `structure_ids`) présente dans les *authorships* sources est donc répliquée dans la table *authorships* canonique, pour deux raisons:
    - optimiser les requêtes;
    - servir de source d'autorité ultime en cas d'erreur dans une des sources (une *authorship* source peut être `excluded`).

```mermaid
flowchart LR
    source_publications---A
    source_authorships---source_publications
    source_authorships---C

    subgraph vérité
    direction LR
    A[publications]-->B[authorships]
    C[persons]-->B
    B---F[structures]
    end
    classDef valid  fill:#af5
    class F,A,C,B valid;
```
