# Chantier — Déduplication des publications sans identifiant fiable (arête pairwise-gated)

## Contexte

Issu de [DATA_publications-match-or-create](DATA_publications-match-or-create.md) (Phase 3, item 3.2b, renvoyé ici). La déduplication repose sur des **tokens de confirmation par égalité** — DOI, NNT, hal_id, pmid, composite thèse `(title_normalized, pub_year)` — qui entrent dans `connected_components` (`domain/entity_resolution.py`) : deux `source_publications` partageant un token sont reliées, la composante est l'œuvre. Couvre les œuvres à **identifiant fiable**.

Restent les types **sans identifiant fiable** : `conference_paper` (~29 500 SP), `book_chapter` (~18 800), `poster` (~3 500). Des records qui partagent souvent un **titre + année sans DOI/hal_id partagé**.

La difficulté est de trancher, entre deux records au même titre+année, **même œuvre vs œuvres distinctes-mais-apparentées** :

- **Versions** (preprint / article publié) : DOI différents → cannot-link → **relation**, déjà géré (« DOI = identité », cf. [METIER_relations-publications](METIER_relations-publications.md)).
- **Dépôts multiples** de la même œuvre (plusieurs dépôts HAL, ou HAL + OpenAlex sans DOI partagé), souvent avec un **typage incertain** (une communication tantôt typée `article`, `book_chapter`, « communication dans un congrès »…) → à **fusionner**.
- **Collision de titre fortuite** (deux œuvres distinctes, même titre+année) → à **ne pas fusionner**.

Le discriminant entre les deux derniers = les **auteurs** : mêmes auteurs ⇒ même œuvre, auteurs différents ⇒ œuvres distinctes. C'est le rôle de la **garde pairwise**.

**Conséquence sur le blocking** : le typage étant incertain, la clé de blocage ne peut pas être `doc_type`-stricte (la même œuvre typée différemment ne co-bloquerait pas). Bloquer sur `(title_normalized, pub_year)` avec garde de longueur, type mis de côté — ou corriger les types en amont.

## Cadre conceptuel — token vs garde pairwise

- **Token** — le signal est une **égalité** (DOI, NNT, thèse `(titre, année)`) : relation transitive → on range par valeur (`GROUP BY`), zéro comparaison. *Tout signal bucketable doit devenir un token* — c'est la pression de design.
- **Garde pairwise** — le signal **n'est pas bucketable**. L'accord d'auteurs est un **recouvrement** (sous-ensemble, noms compatibles), pas une égalité ; non transitif (`{Dupont}` ⊂ `{Dupont, Martin}` ⊄ `{Martin, Durand}`) → pas de clé canonique → comparaison **paire à paire**.

Le **blocage** `(titre, année)` est, lui, un `GROUP BY` **lossy** (sur-groupe les collisions de titre) : il génère les candidats à coût réduit, la garde tranche dans le bloc.

## Méthode — paliers de blocage, du strict au lâche

On part du blocage **le plus strict** et on **desserre par paliers**, chaque desserrage compensé par des gardes plus restrictives. À chaque palier : audit → mesure → décision (égalité composite suffisante = token ? garde de longueur / drop des stop-titles ? garde auteurs ? restreindre les `doc_type` concernés ?). On ne desserre **jamais** sans avoir mesuré le palier courant ; le mécanisme se construit **à la demande**, avec son premier consommateur réel — pas d'abstraction spéculative.

## Mécanisme — token (palier strict) ou arête gardée (palier lâche)

Selon le palier, deux formes (cf. cadre) :

- **Token composite** quand le blocage est assez sélectif pour que l'**égalité** suffise (hypothèse à contrôler par l'audit, type par type) : entre nativement dans `connected_components` (`domain/entity_resolution.py`), comme la thèse. Zéro comparaison.
- **Arête pairwise-gated** quand on desserre et que l'égalité ne suffit plus : pour les records co-bloqués, évaluer l'accord d'auteurs ; si oui, **armer l'arête** (l'ajouter au graphe), sinon les laisser séparés. La projection `domain/source_publications/keys.py` reste la définition des tokens ; les arêtes gardées sont un second canal.

**Cannot-link DOI** préservé à tout palier : ni token ni arête gardée ne fusionnent deux DOI distincts.

## Phases — par palier, du strict au lâche

- [x] **Tier 1 — audit** (fait, sur prod ; blocs `(doc_type, pub_year, title_normalized)` identiques **avec au moins un DOI null**). Résultat : **recouvrement d'auteurs 96-98 %** (même-œuvre). Le résidu « auteurs disjoints + titre long » (~0,25-0,4 %) est **dominé par des échecs de matching de noms** (accents `traoré/traore`, noms composés `le moing`/`berton-charrière`, initiales, listes d'auteurs tronquées selon la source), **pas** par des collisions → **vraie collision ≈ 0,05 %** (~6-9 blocs sur 12 851). **Hypothèse A confirmée** : `(doc_type, pub_year, title_normalized)` + garde de longueur ≈ **token quasi-pur**. La garde auteurs pairwise est **différée** (faible valeur ici, et c'est précisément le matching de noms qui flanche) ; le levier des rares collisions = titre court/générique (garde de longueur) et, pour les chapitres, `container_title` (plus tard).
- [x] **Tier 1 — matérialiser** (en cours) : token `metadata_block = (doc_type, title_normalized, pub_year)`, gardé par `length(title_normalized) > 30`, dans `domain/source_publications/keys.py` + branche de l'univers de `reconcile_components`. Pas de garde auteurs.
- [ ] **Paliers suivants — desserrer** (`(pub_year, title_normalized)`, `doc_type` mis de côté) sur les **couples de `doc_type` audités**, avec garde pairwise (auteurs) plus stricte. Un palier = un audit + une décision (quels couples, quelles gardes).
- [ ] **`book_chapter` — cas à part** (hors paliers titre) : la difficulté n'est pas le titre (« même ouvrage + même titre = même chapitre ») mais d'avoir l'identité du **conteneur** (l'ouvrage) comme clé de blocage. Recoupe la correction chapitre/chapitre de la fiche d'origine.

## Questions ouvertes

- **Précision de la garde auteurs** : quelle forme de recouvrement (premier auteur seul, recouvrement de noms avec seuil, sous-ensemble strict) — mesurer par type les faux positifs (collisions fusionnées à tort) et faux négatifs (même œuvre non fusionnée).
- **Comparaison de deux listes d'auteurs (vrai problème de design)** : matcher des noms qui divergent — noms composés (« Le Goff », « Da Silva »), initiales (« J. Dupont » vs « Jean Dupont »), ordre nom/prénom, accents, translittération. `names_compatible` (domain) existe mais reste **heuristique/bricolage** — à reprendre proprement avant d'en faire le cœur de la garde, d'autant qu'ici on compare des **listes** (recouvrement), pas deux noms isolés. Tension d'ordre à noter : une comparaison par `person_id` **résolu** serait robuste et contournerait le matching de noms, mais les personnes sont résolues **après** la phase publications — au moment de la dédup on ne dispose que des **noms bruts**. Donc matching de noms requis à ce stade (sauf à revoir l'ordre des phases). `persons` ne peut pas simplement précéder `publications` (le matching des personnes est cross-source). Trois options d'ordonnancement, à trancher au premier type : (a) une réconciliation **supplémentaire après `persons`** (cohérence immédiate, 2ᵉ passe) ; (b) **séparer le matching cross-source** du reste de `persons` et le placer après `publications` ; (c) **assumer au run n+1** — si la résolution des personnes change le tableau, elle **re-dirtie** les SP concernées → re-réconciliées au run suivant (convergence éventuelle, naturelle dans le modèle dirty/réconciliation ; coût : une œuvre peut rester non-dédupliquée jusqu'à n+1). Immédiateté (a/b) vs simplicité (c).
- **Typage incertain → égalité de `doc_type` requise a priori.** Position de départ (à confirmer/affiner par l'audit, jamais figée a priori) : deux records ne fusionnent que s'ils ont le **même `doc_type`** ; les fusions cross-`doc_type` ne sont admises qu'en **exceptions avérées** par la mesure, pas par une règle inventée d'avance. Le cas général repose sur les **corrections de métadonnées en amont** pour normaliser le typage avant la dédup ; un même-œuvre mistypé non corrigé **ne fusionne pas** — assumé comme trou de qualité, pas comme défaut de la dédup.
- **Versions sans DOI distinctif** : le `doc_type` **porte** le signal version (preprint vs publié). Sous la règle « égalité de `doc_type` requise », preprint et publié ne fusionnent pas (types différents) — les versions sont donc séparées par le `doc_type` quand le DOI manque. La conflation ne survient que sur `doc_type` **mal rempli** (un preprint typé `article`) → qualité de données, corrigeable en amont. Fréquence réelle à mesurer.
- **Thèse mistypée sans `journal_id`** (renvoyée depuis la fiche d'origine) : SP typées thèse portant un DOI éditeur sans `journal_id` (~69 au stock, dont 3 partageant un DOI avec un article). Relève d'une **correction de `doc_type`** (étendre `THESIS_WITH_JOURNAL_TO_ARTICLE` au signal DOI éditeur, unaire ou relationnel), pas de la dédup pairwise — mais à traiter dans le même mouvement d'étoffement des règles.
- **Contrôles admin — opt-out (matière pour un futur chantier dédié).** Vu la qualité du signal (tier 1 ≈ 99,95 % de même-œuvre), modèle **opt-out** : on fusionne d'office, on contrôle a posteriori. Pièces à construire (futur chantier « contrôles admin », sur la fusion des publications, et **potentiellement des personnes** si leur fusion est réalignée sur le même schéma token/partition) :
  - **Détecteur de fusions suspectes** = les requêtes d'audit réutilisées (recouvrement d'auteurs faible/absent, titre court/générique, `container_title` divergent pour les chapitres, bloc anormalement gros) → vue « à réviser ».
  - **Persistance du verdict admin, ancrée `source_publications`** (jamais sur `publications`, dérivées/éphémères — recréées avec un nouvel id à chaque réconciliation, contrainte sur `pub_id` fragile) :
    - **dé-fusion** = **discriminateur de split** (token *négatif* : valeurs distinctes ⇒ ne co-clusterisent pas ; défaut uniforme = no-op) → 3ᵉ dimension de partition `composante ∩ DOI ∩ tag_split` ;
    - **fusion forcée** = token *positif* admin (valeur commune ⇒ clusterisent), miroir.
  - Les deux survivent à la re-réconciliation et se branchent sur les deux canaux **existants** (tokens / partition). Sans aucune dépendance à `distinct_publications` (qui n'est **plus lu par le pipeline**). Le reconcile actuel ne partitionne **que par DOI** — l'ajout d'un cannot-link admin (consulté par le clustering) sera le premier consommateur de ce canal.

## Liens

- [DATA_publications-match-or-create](DATA_publications-match-or-create.md) — fiche d'origine : tokens de confirmation, réconciliation unifiée merge+split, ancre DOI, vocabulaire token/garde-pairwise. L'item 3.2b y renvoie ici.
- [METIER_doc-types](METIER_doc-types.md) — nomenclature canonique des `doc_type` (et typage incertain des communications).
- [METIER_relations-publications](METIER_relations-publications.md) — versions (preprint/publié) et identifiants secondaires pontant deux DOI = relations, pas fusions.
