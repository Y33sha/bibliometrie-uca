"# Chantier — Déduplication des publications sans identifiant fiable (arête pairwise-gated)

## Contexte

Issu de [DATA_publications-match-or-create](DATA_publications-match-or-create.md) (Phase 3, item 3.2b, renvoyé ici). La déduplication repose sur des **tokens de confirmation par égalité** — DOI, NNT, hal_id, pmid, composite thèse `(title_normalized, pub_year)` — qui entrent dans `connected_components` (`domain/publications/clustering.py`) : deux `source_publications` partageant un token sont reliées, la composante est l'œuvre. Couvre les œuvres à **identifiant fiable**.

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

Le **blocage** `(titre, année)` est, lui, un `GROUP BY` **lossy** (sur-groupe les collisions de titre) : il génère les candidats à coût réduit, la garde tranche dans le bloc. Le recouvrement (et non l'égalité) s'impose car les listes d'auteurs sont **tronquées** selon la source — d'où un matching de noms délicat (cf. question ouverte).

Garde **symétrique** (un signal assez fort pour fusionner l'est pour défusionner). Elle ne sépare pas les **versions** (preprint/publié ont les mêmes auteurs — c'est le DOI qui les sépare → relation) ; son rôle est « même titre+année sans DOI distinctif » : départager dépôt-multiple de collision.

## Méthode — audit empirique par type

On n'ajoute **pas** un type sans mesurer. Recette : sur les blocs `(title_normalized ≥ seuil, pub_year)` à ≥2 records **sans DOI partagé**, vérifier si le recouvrement des auteurs (premier auteur, ou recouvrement de noms) départage proprement même-œuvre vs collision (mesurer faux positifs et faux négatifs). Construire le mécanisme **à la demande**, avec son **premier consommateur réel** — pas d'abstraction spéculative.

## Mécanisme à construire (quand le premier type le justifie)

Une **arête pairwise-gated** dans la réconciliation (`reconcile_components`) : pour les records co-bloqués (même titre+année, garde de longueur), évaluer l'accord d'auteurs ; si oui, **armer l'arête** (l'ajouter au graphe que voit `connected_components`), sinon les laisser séparés. Distinct du token (qui entre nativement) ; symétrique (cf. cadre). La projection partagée `domain/source_publications/keys.py` reste la définition des tokens ; les arêtes gardées sont un second canal. **Cannot-link DOI** préservé : une arête gardée ne fusionne jamais deux DOI distincts.

## Phases (à dérouler par type, empiriquement)

- [ ] **conference_paper** — audit : parmi les blocs titre+année sans DOI partagé, l'accord d'auteurs sépare-t-il same-work des collisions ? Premier consommateur probable du mécanisme.
- [ ] **poster** — idem `conference_paper` (probablement même forme).
- [ ] **book_chapter** — la difficulté n'est pas les titres (« même ouvrage + même titre = même chapitre ») mais d'avoir l'identité du **conteneur** (l'ouvrage) comme clé de blocage. Recoupe la correction chapitre/chapitre de la fiche d'origine (Phase 2).

## Questions ouvertes

- **Précision de la garde auteurs** : quelle forme de recouvrement (premier auteur seul, recouvrement de noms avec seuil, sous-ensemble strict) — mesurer par type les faux positifs (collisions fusionnées à tort) et faux négatifs (même œuvre non fusionnée).
- **Comparaison de deux listes d'auteurs (vrai problème de design)** : matcher des noms qui divergent — noms composés (« Le Goff », « Da Silva »), initiales (« J. Dupont » vs « Jean Dupont »), ordre nom/prénom, accents, translittération. `names_compatible` (domain) existe mais reste **heuristique/bricolage** — à reprendre proprement avant d'en faire le cœur de la garde, d'autant qu'ici on compare des **listes** (recouvrement), pas deux noms isolés. Tension d'ordre à noter : une comparaison par `person_id` **résolu** serait robuste et contournerait le matching de noms, mais les personnes sont résolues **après** la phase publications — au moment de la dédup on ne dispose que des **noms bruts**. Donc matching de noms requis à ce stade (sauf à revoir l'ordre des phases).
- **Typage incertain** : la même œuvre typée différemment selon le dépôt ne co-bloque pas si la clé inclut `doc_type`. Bloquer hors type, ou corriger les types en amont — à cadrer.
- **Versions sans DOI distinctif** : preprint + publié au même titre+année, mêmes auteurs, sans DOI pour les séparer → la garde auteurs les fusionnerait, alors que c'est *peut-être* une relation. Cas limite : à mesurer (fréquence réelle) avant de décider.
- **Thèse mistypée sans `journal_id`** (renvoyée depuis la fiche d'origine) : SP typées thèse portant un DOI éditeur sans `journal_id` (~69 au stock, dont 3 partageant un DOI avec un article). Relève d'une **correction de `doc_type`** (étendre `THESIS_WITH_JOURNAL_TO_ARTICLE` au signal DOI éditeur, unaire ou relationnel), pas de la dédup pairwise — mais à traiter dans le même mouvement d'étoffement des règles.

## Liens

- [DATA_publications-match-or-create](DATA_publications-match-or-create.md) — fiche d'origine : tokens de confirmation, réconciliation unifiée merge+split, ancre DOI, vocabulaire token/garde-pairwise. L'item 3.2b y renvoie ici.
- [METIER_doc-types](METIER_doc-types.md) — nomenclature canonique des `doc_type` (et typage incertain des communications).
- [METIER_relations-publications](METIER_relations-publications.md) — versions (preprint/publié) et identifiants secondaires pontant deux DOI = relations, pas fusions.
