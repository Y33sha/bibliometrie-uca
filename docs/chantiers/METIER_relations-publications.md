# Chantier — Relations entre publications

Commencé le 2026-06-21

Modéliser les relations sémantiques entre publications **distinctes** (qui ne sont pas des doublons) : supplément ↔ article, actes/ouvrage ↔ communication/chapitre, preprint ↔ version publiée, article ↔ erratum/rétractation, data paper ↔ jeu de données décrit.

## Contexte

Les relations entre œuvres distinctes sont aujourd'hui perdues : chaque DOI donne une publication indépendante, sans lien explicite vers ses œuvres apparentées.

Deux clarifications fixent le périmètre :

- **« Même œuvre » n'est pas une relation, c'est de la déduplication** — déjà traitée. Les versions d'un dépôt DataCite (`IsVersionOf`, `HasVersion`, `IsIdenticalTo`, `IsNewVersionOf`) convergent sur le DOI concept à la phase `metadata_correction` (correction de DOI par cluster). Les DOI alternatifs d'une même œuvre vus par OpenAlex/ScanR vivent dans `external_ids.related_dois` et nourrissent dédup et cross-import. Tout cela est hors scope ici.
- **Les citations ne sont pas des relations d'œuvre.** Les `relatedIdentifiers` DataCite de type `References` / `Cites` / `IsCitedBy` représentent le graphe bibliographique (ordre de grandeur : ~10 500 liens, très majoritairement hors corpus). Hors scope.
- **Les rapports de peer-review sont probablement hors scope** (à vérifier en Phase 0). Le `has-review` / `is-reviewed-by` (Crossref) lie une œuvre à son évaluation, pas à une œuvre apparentée au sens visé ici.

### La matière est déjà ingérée

Les relations déclarées par les sources sont captées par les normalizers et stockées sur `source_publications` :

- **DataCite** : `meta.related_identifiers` — liste typée `[{doi, relation_type}]` (vocabulaire `IsSupplementTo`, `IsPartOf`, `HasPart`…).
- **Crossref** : `meta.relation` — vocabulaire distinct (`is-preprint-of`, `has-preprint`, `has-review`…).

Le chantier ne porte donc pas sur l'ingestion, mais sur la **modélisation**, la **dérivation au niveau des publications canoniques**, et l'**exposition**.

### Deux signaux sûrs

1. **Relations déclarées par les sources** (ci-dessus) : typées, explicites.
2. **Clés de confirmation partagées, scindées par DOI distinct.** Le matching (`reconcile_components`) cluster les `source_publications` par clés (DOI, NNT, hal_id, PMID, arXiv…) puis partitionne par DOI (cannot-link sur DOI distinct). Deux publications qui **partagent une clé** mais portent des **DOI distincts** sont par construction apparentées sans avoir fusionné — un signal de relation déterministe, dérivable d'une simple requête « même clé sur des `publication_id` distincts ». Le *type* se déduit des `doc_type` des deux bouts (preprint + article → preprint↔publié). Ordre de grandeur au 2026-06-21 : hal_id 395, arXiv 112, PMID 33, NNT 14.

La détection vraiment **heuristique** (rapprochement par titre pour les orphelins sans clé ni relation déclarée) est distincte de ces deux signaux sûrs, et reportée en fin de chantier.

### Cas particuliers observés

- **Déclencheur historique — suppléments figshare orphelins.** Des datasets figshare dont le titre référence un article parent absent de la base. Désormais *data-driven* : le supplément porte `IsSupplementTo → DOI parent` ; inutile de retrouver le parent par titre. S'il est en corpus → relation ; sinon il est rapatriable par cross-import.
- **Pièces intra-package.** `IsPartOf` / `HasPart` sont majoritairement des **sous-fichiers d'un même dépôt** de données (cible = DOI parent, porteur = parent + suffixe, même préfixe ; ordre de grandeur ~1150 sur datasets). Ce ne sont pas des œuvres distinctes : à **collapser** dans le dépôt parent (déduplication), pas à modéliser en relation. Une minorité (~200 : actes ↔ communication, ouvrage ↔ chapitre) est en revanche une vraie relation structurelle.
- **Types dépendants.** Certains types n'existent qu'en relation à un autre : erratum et rétractation (totalement dépendants d'un article corrigé/rétracté), preprint (non auto-suffisant — antérieur à une publication qui peut ne jamais venir). Une publication d'un type dépendant **sans** sa relation naturelle est une anomalie à remonter.

## Décisions

1. **Périmètre = œuvres distinctes liées.** Même-œuvre (versions, formes identiques) et citations sont exclues.
2. **Les pièces intra-package sont collapsées en déduplication, pas modélisées en relation** — dans `metadata_correction`, en généralisant le motif `IsPartOf`-même-package. (La règle figshare actuelle `DOI_FIGSHARE_COLLECTION_TO_DATASET` ne fait que reclasser le conteneur en `dataset` ; elle ne collapse pas les pièces.)
3. **Population à partir des deux signaux sûrs** (relations déclarées + clés partagées scindées par DOI). La détection heuristique vient après, en complément.
4. **Table dédiée `publication_relations`** plutôt qu'une colonne sur `publications` ou un calcul à la volée. La cible peut être un **DOI hors corpus** ; l'UI requête les deux sens ; la détection ultérieure y écrit aussi. La vérité-source reste sur les `source_publications` (`meta`) ; la phase en **dérive** le niveau canonique.

   Forme envisagée :

   ```
   publication_relations (
       from_publication_id  integer NOT NULL REFERENCES publications,
       relation_type        text    NOT NULL,   -- vocabulaire canonique
       target_doi           text    NOT NULL,   -- cible (en corpus ou non)
       target_publication_id integer REFERENCES publications,  -- résolu si en corpus
       source               text    NOT NULL    -- provenance du signal
   )
   ```

5. **Nouvelle phase pipeline, après `publications`** (donc après `metadata_correction` qui a collapsé même-œuvre et pièces de package, et après l'assignation des publications canoniques qui permet de résoudre les cibles en `publication_id`).
6. **Vocabulaire canonique unifié.** Un mapping des types DataCite et Crossref vers un jeu de types canoniques (analogue à `domain.source_publications.doc_types`), à figer en Phase 0.

## Phasage

### Phase 0 — Audit + périmètre

- [x] Vocabulaire canonique figé dans `domain/publications/relations.py` (in scope : preprint, supplement, part, correction, retraction, translation, describes ; hors scope : citations, même-œuvre, peer-review). (b1cd2df8)
- [x] Signal erratum/rétractation/correction : confirmé côté Crossref `relation` (familles `erratum` / `correction` / `retraction`, portées par l'article ; absent des `relatedIdentifiers` DataCite).
- [x] Cibles `describes` (Crossref `is-part-of`) confirmées datasets (data paper → dataset).
- [x] `IsVariantFormOf` tranché : **dédup** (copie repository → version publiée, DOI distincts mais même œuvre déclarée), traité en Phase 1 — pas une relation.
- [x] `is-comment-on` / `has-comment` audité : porteur de doc_type `peer_review` → **hors scope** (comme `has-review`).
- [x] `expression_of_concern` (Crossref) inclus comme famille `has_concern` / `is_concern_about` (avis éditorial post-publication, signal qualité).

### Phase 1 — Dédup des formes secondaires DataCite

- [x] Trois cas de convergence même-œuvre dans la correction de DOI par cluster (`metadata_correction`) : version → concept (`IsVersionOf`, déjà en place), forme variante → version publiée (`IsVariantFormOf`), fichier d'un dépôt → dépôt parent (`IsPartOf` dont le DOI porteur = parent + suffixe). Sur la base courante : 916 substitutions variante + 108 pièces de package. (f5c081dd)

### Phase 2 — Modèle + population

- [x] Table `publication_relations` + enum `relation_type` (migration). (9e0a599a) Vocabulaire canonique `domain/publications/relations.py`. (b1cd2df8)
- [x] Population signal #1 : relations déclarées (`meta.related_identifiers`, `meta.relation`), nouvelle phase `relations` après `publications`, cibles résolues en `publication_id`. Sur la base courante : 3372 relations (2102 cibles en corpus). (2e0d3951)
- [x] Population signal #2 : paires de publications distinctes (DOI distincts) partageant une clé de confirmation (hal_id, arXiv, PMID, NNT), type déduit du couple de `doc_type` (`infer_shared_key_relation`). Couples typés → relation précise dirigée : `preprint` → `is_preprint_of`, `erratum` → `is_correction_of`, `dataset` → `is_supplement_to`, ouvrage ↔ chapitre → `is_part_of` ; couples contenant `peer_review` exclus ; tout le reste (dont deux exemplaires d'une même œuvre à DOI distincts non fusionnés) → `is_related_to`, type symétrique « apparenté, à qualifier » (nouvelle valeur d'enum, migration `f1a7c3e9b2d4`). `source = 'shared_key'`, recalculé indépendamment du signal #1. Un `is_related_to` n'est **pas** posé si la paire porte déjà une relation précise du signal #1 (`fetch_declared_related_pairs`) — sinon doublon vague redondant.
- [x] Les `target_doi` rejoignent le pool moissonné par cross-import (`get_cross_import_dois`), pour rapatrier les œuvres liées absentes. Les types exclus n'étant pas dans la table, rien d'indésirable n'est rapatrié. (6db0e048)

### Phase 3 — UI

- [x] Afficher les publications liées sur la fiche détail (`RelatedPublications.svelte`, sous le header, avant les sujets). Relations des deux sens, le type entrant inversé pour se lire depuis la publication courante (`inverse_relation`), groupées par type ; cible au corpus → lien interne, cible hors corpus → lien `doi.org`. Exposées par `get_publication_relations` dans la réponse détail.
- [x] Page détail — relations **vers le parent** (la publi est une pièce dépendante : erratum, préprint, supplément, partie…) mises en avant dans le header : bandeau voyant (fond teinté + filet d'accent) sous le titre, « Correction de / Préprint de / Supplément à … » + titre cliquable de l'œuvre principale. Le tri vit dans `PARENT_RELATION_TYPES` (`$lib/labels`).
- [ ] Page détail — relations **dépendantes** (`has_*`) et **latérales** (`is_related_to`, data paper ↔ dataset) : à déplacer du bloc central vers la sidebar (à tester d'abord — risque d'enlaidir avec un titre coupé/wrappé).
- [ ] Réfléchir aux pages listes: publications "dépendantes" exclues par défaut? option de les inclure? distinguer vue tabulaire (totale) vs vue liste (avec groupement des publications liées)?

### Phase 4 — Exploitations en aval

Le retypage à partir des relations **déclarées (signal #1)** se fait en règle de `metadata_correction` au niveau SP, **pas** en lecture de `publication_relations` : la relation déclarée vit dans `meta` (disponible en amont) et est indépendante du `doc_type`, donc acyclique — alors que le signal #2 *dérive* le type du `doc_type` et ne doit jamais le rétro-alimenter. Le retypage durcit le `doc_type` avec un fait source-autoritaire ; comme Crossref/DataCite sont prioritaires sur le type, la correction gagne l'arbitrage canonique.

- [x] Retypage preprint : une SP déclarant `is-preprint-of` (Crossref `meta.relation`) *est* un preprint → règle `PREPRINT_RELATION_TO_PREPRINT` dans `metadata_correction` (prédicat `declares_preprint` calculé au fetch). Corrige le cas fréquent où Crossref ne type pas le record (`doc_type` nul) et où l'arbitrage prenait `article` d'OpenAlex.
- Retypage des data papers : **abandonné**. Une SP déclarant `describes` n'est pas un data paper au sens strict — un article référence souvent des datasets sans en être un (audit : 78 des 104 déclarants sont des articles, légitimement). Pas de règle automatique.
- Retypage erratum / rétractation depuis la relation : **non viable**. Les `is_correction_of` déclarés sont quasi inexistants (4) et **auto-référentiels** (le DOI corrigé = celui de la publication, artefact Crossref) — ce ne sont pas des erratums. La détection des erratums reste portée par le préfixe de titre (`TITLE_ERRATUM_PREFIX_TO_ERRATUM`). La complétude de cette détection (erratums sans préfixe reconnu) est un audit distinct.
- [ ] Audit des relations multiples : le critère d'anomalie n'est **pas** « > 1 relation » mais « ≥ 2 types **précis non-inverses** » sur une même paire. Sur la base courante (761 paires multi-types) : 746 sont de la **redondance inverse** (`has_preprint`+`is_preprint_of`, `describes`+`is_described_by` — le même lien déclaré par les deux bouts, by-design, l'UI le dédoublonne par `(type inversé, doi)`), ~12 étaient un `is_related_to` chevauchant le signal #1 (désormais supprimé à la population), et seulement **3** sont de vraies anomalies (rôles précis contradictoires) — à remonter à la main.
- [ ] Audit des orphelins : remonter les publications de type dépendant (erratum, rétractation) sans relation naturelle. Les preprints sont exclus — un preprint sans version publiée est normal (antérieur à une publication qui peut ne jamais venir). Sur la base courante : **148 erratums sur 233** (63 %) et **les 9 rétractations** n'ont aucun lien vers l'article corrigé/rétracté (le signal déclaré est quasi absent : `is_correction_of` auto-référentiels, aucune relation de rétractation). Ils sont correctement **typés** (préfixe de titre) mais non **reliés**.
- [x] Rapprochement par titre — **signal #3 de la phase `relations`**, deux variantes sous garde d'ambiguïté commune (longueur de titre > 30 ; abstention dès que plus d'un parent **substantiel**, hors formes de la même œuvre, porte le titre) :
  - **erratums** → `is_correction_of` : le titre reproduit celui du parent après un préfixe (« Erratum: », « Corrigendum to »…), donc le `title_normalized` du parent en est un **suffixe**. Fenêtre [n−2 … n]. ~68 orphelins rattachables.
  - **preprints** → `is_preprint_of` : le preprint et sa version publiée portent un titre **identique**. Fenêtre [n … n+2]. ~240 liens nets. Précision validée contre la vérité-terrain (relations déjà établies) : 423/429 = 98,6 % désignent le même parent → **pas de garde auteurs nécessaire**.
- [x] **`target_doi` nullable** (migration `c1a8e4f7b2d9`) : une relation peut cibler une œuvre **au corpus sans DOI** (désignée par `target_publication_id`). La PK passe sur un `id` de substitution, l'unicité sur `(from_publication_id, relation_type, target_publication_id, target_doi)` `NULLS NOT DISTINCT`. Le `CHECK` garantit qu'une cible existe (publication ou DOI).
- [x] Rapprochement par titre — **rétractations** : audité, **abandonné**. Les 9 notices au stock préfixent bien (« Retraction notice to «…» », « Retraction Note: … »), mais **aucune** n'a son article rétracté au corpus (0 parent, même en sous-chaîne — l'œuvre rétractée n'est pas une publication UCA). Rien à relier par titre ; relèvera de l'interface admin (ou d'un rapatriement par DOI si un signal déclaré le portait).

## Questions ouvertes

- **`IsVariantFormOf`** (ordre de grandeur ~890, très majoritairement en corpus) : même œuvre sous une autre forme → déduplication (étendre la logique concept) ou relation ? Tranche le périmètre.
- **Signal erratum/rétractation ↔ article** : pas de `relatedIdentifier` dédié ; à localiser (Crossref `relation`, ou inférence depuis le `doc_type` erratum + une clé/titre partagé).
- **Vocabulaire canonique** : liste exacte des types retenus et mapping depuis DataCite et Crossref.
- **Cardinalité et direction** par type de relation.
- **Cibles hors corpus** : relation conservée vers le DOI nu ; le rapatriement via cross-import (Phase 2) les fera entrer si elles sont accessibles.
- **Effet sur le périmètre / la dédup** : un supplément orphelin hors périmètre, marqué comme lié — conservé avec un drapeau ou écarté ?

## Liens

- Correction de DOI par cluster (déduplication même-œuvre + ouvrage/chapitre) : `application/pipeline/metadata_correction/correct_by_cluster.py`, règles dans `domain/source_publications/correction.py`.
- Relations déclarées ingérées : `source_publications.meta` (`related_identifiers` côté DataCite, `relation` côté Crossref).
- Pool cross-import par DOI : `infrastructure/sources/common.py::get_cross_import_dois`.
- Source DataCite (origine des `relatedIdentifiers`) : `docs/sources/07-datacite.md`.
