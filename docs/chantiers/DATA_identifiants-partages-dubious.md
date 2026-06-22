# Chantier — Identifiants partagés entre signatures (corruption source) : généraliser le `_dubious`

## Contexte

Une personne « Frankenstein » découverte sur le stock : la personne 12913 (Acharya, Shreyasi, autrice ALICE/CERN) porte **921 formes de nom** — en majorité des **noms d'autres auteurs** (Adamová, Agnello, Das, Kim…) — et **2122 authorships couvrant 920 noms distincts**.

Mécanisme établi par l'investigation :

- L'attribution s'est faite **par identifiant** : l'ORCID confirmé `0000-0002-9213-5329` est porté par 1570 de ses authorships, couvrant 920 noms distincts.
- La cause est **en amont, dans la source**. Le payload crossref d'un seul papier ALICE (`10.1103/physrevc.108.055203`) compte 1042 auteurs, dont **928 portent le même ORCID** `0000-0002-9213-5329` (918 noms distincts) : le dépôt crossref de la collaboration colle l'ORCID du premier auteur sur quasiment tous les co-auteurs. OpenAlex hérite de la corruption.
- Le pipeline a fait confiance à l'ORCID comme identifiant fiable — correctement selon ses règles — mais **l'identifiant est empoisonné à la source**.
- Les formes de nom sont un **amplificateur secondaire** : une fois ces authorships rattachées par ORCID, leurs noms deviennent des formes de nom de la personne, qui attirent ensuite d'autres authorships par matching de nom.

Le cas n'est pas isolé : tout auteur fréquent de méga-papers (physique des particules notamment) peut être agglomératé de la même manière. Un identifiant partagé suffit à enclencher la spirale.

## Le garde-fou existe déjà pour HAL — il faut le généraliser

`application/pipeline/normalize/normalize_hal.py` traite exactement cette pathologie pour `hal_person_id` : au normalize, par enregistrement, un `hal_person_id` porté par **≥2 positions d'auteur distinctes** est jugé corrompu (un même compte ne peut pas désigner deux signatures dans un même dépôt). Toutes les positions concernées voient **tous** leurs identifiants (hal_person_id, idref, idhal, orcid) suffixés `_dubious` : valeur conservée (réversible, diagnosticable) mais **invisible au matching**, qui lit les clés non suffixées. Idempotent, recalculé depuis le brut à chaque passe. Un oneshot `interfaces/cli/oneshot/backfill_dubious_hal_identifiers.py` l'applique au stock déjà normalisé.

Ce qui manque : la même garde sur les **autres identifiants et les autres sources**. La corruption ORCID vient de crossref et openalex, qui n'ont aucune garde équivalente. Plutôt que de dupliquer la logique HAL dans chaque normalizer, on l'**abstrait**.

## Principe

Un identifiant (de n'importe quel type) porté par **≥2 positions d'auteur distinctes au sein d'un même enregistrement source** est une corruption : un identifiant ne peut pas désigner deux signatures dans un même document. Toute position portant une valeur partagée voit **tous** ses identifiants requalifiés `_dubious` — conservés, mais ignorés au matching.

Décision sémantique assumée : on requalifie **toutes** les positions portant la valeur partagée, **y compris celle du vrai propriétaire**. Dans le cas ALICE, l'ORCID est sur 928 positions dont la vraie Acharya ; on est incapables de désigner la bonne, donc on sacrifie le match par identifiant sur ce papier (la personne matchera par nom) pour ne pas mal-attribuer les autres. C'est le comportement HAL actuel, et le choix conservateur correct.

La requalification est une **dérivation du normalize** (calculée depuis le brut, recalculée à chaque passe, idempotente), pas une mutation de correction a posteriori : elle est compatible avec l'inviolabilité des tables `source_*`.

## Remédiation du stock déjà corrompu

La phase `persons` (`create_persons_from_source_authorships`) est **incrémentale** (`WHERE person_id IS NULL`) : les authorships déjà rattachées ne sont pas ré-évaluées. Il faut donc les rendre à nouveau éligibles.

Contrainte d'ordonnancement (vérifiée) : les formes de nom sont une **pure dérivation** de `source_authorships.person_id`, reconstruites par `populate_person_name_forms` (recompute + diff avec DELETE). Or l'ordre normal de la phase est `create_persons` **puis** `populate`. Si on se contente de remettre les `person_id` à NULL et qu'on relance, `create_persons` re-matche par nom sur les formes encore corrompues **avant** leur purge → re-corruption immédiate.

La séquence de remédiation doit donc être : **`null person_id corrompus` → `populate` (purge des formes) → `create` (re-matche, ORCID empoisonné désormais `_dubious`) → `populate` (rebuild final)**.

## Phases

### Phase 1 — Pipeline (le garde-fou)

- [ ] **Helper partagé** (domain, pur) : `mark_shared_identifiers_dubious(ids_by_position)` — détecte les valeurs portées par ≥2 positions (par type d'id) et suffixe `_dubious` à tous les identifiants des positions concernées. Reproduit le comportement HAL, généralisé à tout type d'identifiant.
- [ ] **Migrer normalize_hal** sur le helper (remplacer sa logique `Counter` maison ; non-régression stricte du comportement « blindé »).
- [ ] **Brancher les autres normalizers** : crossref et openalex en priorité (sources de la corruption ORCID et utilisées au matching) ; wos/scanr/datacite par cohérence (garde uniforme, coût nul même si leur ORCID n'est pas un signal de matching).

### Phase 2 — Backfill et remédiation

- [ ] **Backfill oneshot** généralisé (calqué sur `backfill_dubious_hal_identifiers`) : requalifier `*_dubious` sur le stock crossref/openalex (+ autres) déjà normalisé.
- [ ] **Remédiation personnes** : oneshot `null → populate → create → populate`, plus purge des `person_identifiers` (table) qui ne sont plus appuyés par une authorship `in_perimeter`.

### Phase 3 — Tests

- [ ] Le helper (cas partagé / non partagé / vrai propriétaire taint).
- [ ] Un cas par normalizer ; non-régression HAL.
- [ ] La séquence de remédiation.

## Questions ouvertes

- **Identifier les `person_id` à nuller dans la remédiation.** Signature de la corruption : authorship rattachée via un identifiant qui, dans son enregistrement source, est porté par ≥2 noms distincts. Une fois le backfill `_dubious` passé, c'est repérable comme « authorship dont l'identifiant de matching est désormais `_dubious` et qui n'a pas d'autre signal valide ». À préciser : périmètre exact des `person_id` à remettre à NULL (toutes les authorships `_dubious`-isées ? seulement celles sans nom compatible avec la personne actuelle ?).
- **Seuil ≥2.** HAL utilise ≥2 ; un identifiant légitimement présent deux fois dans un même papier est quasi inexistant. Garder ≥2 par cohérence, ou monter le seuil pour les sources très bruitées ? À mesurer.
- **Tainter tous les ids d'une position, ou seulement le type partagé ?** HAL taint tous les ids (l'identité entière de la signature est douteuse, ils sont tous attachés au compte HAL). Pour crossref/openalex, la corruption est spécifiquement l'ORCID, et les autres ids (rares) pourraient être sains — mais tainter tout reste le choix conservateur. À trancher selon la fréquence de co-occurrence d'autres ids.
- **Purge des `person_identifiers` orphelins.** Définir « plus appuyé par une authorship `in_perimeter` » : un identifiant de la table `person_identifiers` (statut/historique) dont plus aucune `source_authorship in_perimeter` ne porte la valeur. Attention aux identifiants `confirmed` manuellement (ne pas supprimer un verdict humain).
- **Ampleur.** Quantifier sur le stock : combien d'ORCID partagés sur N noms distincts, combien de personnes « Frankenstein » en résultent. Dira si la remédiation touche une poignée d'auteurs physique des particules ou un volume plus large.
