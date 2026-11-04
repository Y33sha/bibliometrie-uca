# Chantier — Fiabilité de l'alignement des auteurs

## Contexte

La phase `author_grouping` réunit dans une contribution les contributions sources d'un même auteur dans une publication (`domain/contributions/author_grouping.py`). Des étapes strictes (nom, identifiant, filtre d'ordre, ordre dans les trous) précèdent un modèle probabiliste (Fellegi-Sunter) appliqué au résidu. Les noms de famille et les prénoms se comparent séparément. Plusieurs règles servent aux méga-collaborations, où des auteurs partagent un nom de famille et une initiale.

Au 2026-11-04, les liens se répartissent ainsi : 15 878 841 par le nom, 850 094 par le modèle, 288 071 par l'ordre, 127 535 par identifiant. 90 % des liens du modèle sont dans les publications de plus de 1 000 contributions.

Exemple : la publication 22307 a quatre auteurs dans chacun de ses cinq enregistrements sources. Les trois derniers sont alignés. HAL découpe la première autrice en « fernandes da rocha / carmella puleoto », OpenAlex, WoS et ScanR en « da rocha puleoto / carmella fernandes ». Il reste une contribution source de chaque côté, dans le même trou. Les noms de famille et les prénoms tombent au niveau `else` (Jaro-Winkler 0,52 et 0,84), donc `_position_only` écarte la paire avant le modèle. Les deux noms complets ont pourtant les mêmes mots. La publication a cinq contributions.

## Décisions

- Les variantes se comparent sur un banc de simulation hors base, avant toute modification du pipeline.
- Le temps d'exécution de la phase compte autant que la fiabilité de l'alignement.
- La fiabilité se juge sur les contributions du périmètre. Les homonymes à initiales des méga-collaborations s'alignent au mieux, sans règle dédiée.
- Variante retenue, pour chaque enregistrement source face aux contributions déjà formées :
  1. nom de famille unique des deux côtés ;
  2. nom de famille et prénom complet uniques ;
  3. nom de famille et initiale uniques ;
  4. trous de même taille des deux côtés : comparaison terme à terme, dans l'ordre ;
  5. trous de tailles inégales : meilleures paires ;
  6. résidu entier, sans contrainte d'ordre : meilleures paires, avec un mot identique exigé.
- Comparaison des règles 4 à 6, seuil 0,8 :
  - score mot à mot sur le nom complet, quel que soit le découpage entre nom de famille et prénom : part des mots du nom le plus court retrouvés dans l'autre, avec au moins un mot complet commun. Un mot se retrouve à l'identique, par Jaro-Winkler 0,85 ou plus entre mots de 5 lettres ou plus, ou par son initiale ;
  - « ae », « oe », « ue » rabattus sur « a », « o », « u » ; mots collés fusionnés (« vanhulse » et « van hulse ») ;
  - score de 1 pour un nom de famille inclus dans l'autre avec des initiales de prénom compatibles (« porteboeuf / sarah julie » et « porteboeuf houssais / s »).
- Disparaissent : filtre d'ordre, règles interverties, lien par identifiant, ordre dans les trous, modèle probabiliste et ses poids.

## Phasage

### Phase 1 — Banc de simulation

- [x] Rejeu de l'alignement hors base sur un échantillon stratifié par tranche de nombre de contributions (1, 2-10, 11-100, 101-1000, plus de 1000) : 200, 500, 500, 200 et 40 publications.
- [x] Mesures : contributions par publication face à la plus longue liste d'auteurs, contributions sources regroupées autrement, contributions du périmètre propres à chaque algorithme, temps d'exécution.
- [x] Cas tracés règle par règle : publications 22307, 29120, 257325.

### Phase 2 — Variantes

- [x] Résidu de même taille des deux côtés d'un trou : comparaison des noms complets, indépendante du découpage.
- [x] Critère d'ambiguïté : un seul jeu de règles. Les erreurs restantes concernent des homonymes à initiales des méga-collaborations, hors périmètre.
- [x] Remplacement du modèle probabiliste. Sur l'échantillon, la variante retenue donne autant de contributions que l'algorithme en place, en trois fois moins de temps. Dans le périmètre, 10 publications diffèrent : 2 gains de la variante (jury de thèse entre theses.fr et ScanR, noms composés), 7 répartitions différentes de doublons d'enregistrements sources, 1 erreur de HAL sans bonne réponse.

### Phase 3 — Intégration

- [ ] Variante retenue dans `domain/contributions/author_grouping.py`, avec ses tests.
- [ ] Méthodes de `grouping_method` et colonnes `score` et `margin` de `aligned_source_contributions` : migration.
- [ ] Retrait du modèle : `residual_weights.py`, `interfaces/cli/dev/estimate_residual_weights.py`, dépendances `splink` et `scipy`, champs `score` et `margin` de l'API, compteurs de la phase dans l'administration.
- [ ] Retrait de l'item « Revue des appariements du modèle » de la fiche d'audit de la résolution des personnes.
- [ ] `--rebuild-author-grouping`.

### Phase 4 — Documentation

- [ ] Mise à jour de `docs/pipeline/08-author-grouping.md`.

## Questions ouvertes

- Attribution manuelle d'une contribution orpheline en conflit avec une contribution automatique de la même personne. La contribution épinglée garde la personne, l'autre contribution reste sans personne (`settle_publication`). Sous la centaine d'auteurs, ce conflit révèle surtout un défaut d'alignement ou un doublon d'auteur dans un enregistrement source. Piste : l'épinglage comme contrainte de l'alignement. Les deux contributions fusionnent si elles ont des enregistrements sources disjoints ; sinon, l'une des deux contributions sources est un doublon. La phase `author_grouping` précède la phase `persons`.
- Homonymes à initiales chinoises (« liu / yanlin », « liu / y l ») : un découpage en syllabes pinyin les départagerait. Seulement si le périmètre en souffre.
