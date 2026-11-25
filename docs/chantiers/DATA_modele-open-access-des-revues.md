# Chantier — Modèle open access des revues

## Contexte

Le statut d'une publication à copie ouverte sous licence chez l'éditeur dépend du modèle open access de sa revue : `hybrid` pour une revue sur abonnement, `gold` pour une revue en open access intégral, `diamond` pour une revue diamant. Appliqué à toutes les publications d'une revue, le modèle actuel classe `gold` les articles parus avant son passage à l'open access intégral.

OpenAlex donne l'année de ce passage (`oa_flip_year`). Avant cette année, un article ouvert est hybrid ou bronze ; après, gold. L'aide d'Unpaywall renvoie vers celle d'OpenAlex, produits par la même organisation.

## Décisions

- Le modèle pris en compte est celui de l'année de parution (`domain/serials/oa_model_history.py`). L'année du passage vient d'OpenAlex, sinon du DOAJ. Une revue née en open access intégral d'après OpenAlex garde son modèle pour toutes ses publications. Sans année connue, le modèle est inconnu, donc `hybrid`.
- Le modèle d'une revue vient d'OpenAlex au niveau de la revue (`openalex_is_oa`). Diamond vient du DOAJ et du Diamond Discovery Hub. Un modèle saisi à la main reste en l'état.

## Phasage

### Phase 1 — Modèle daté

- [x] `check_serials_in_openalex` lit `is_oa` et `oa_flip_year`, écrits dans `serials.openalex_is_oa` et `serials.openalex_oa_flip_year`.
- [x] Le calcul du statut open access lit le modèle de la revue l'année de parution.

### Phase 2 — Modèle des revues d'après OpenAlex

- [x] Tâche `model_serials`, après l'import du DOAJ. Suppression du vote d'`attach_serials` sur le modèle donné par les enregistrements sources OpenAlex, et de la clé `oa_model` de `biblio.journal`.

### Phase 3 — Apport d'Unpaywall

- [ ] Mesurer ce que les verdicts d'Unpaywall ajoutent au statut open access des works d'OpenAlex. Décider si Unpaywall reste une source distincte.

## Questions ouvertes

- Mesure du 2026-11-25 : statut open access de chaque publication à verdict Unpaywall, calculé avec et sans le verdict.
    * Couverture du périmètre : 46 217 publications à DOI. 41 973 ont un verdict, 3 715 sont absentes d'Unpaywall, 529 restent à interroger.
    * Le verdict change le statut de 1 088 publications du périmètre, soit 2,6 % des publications à verdict. 953 ont un work OpenAlex, sur 41 766. 135 n'en ont pas, sur 207.
    * 207 publications du périmètre deviennent ouvertes par le seul verdict : 178 avec un work OpenAlex, 29 sans. Parmi elles, 136 passent de `closed` ou `embargoed` à `green`. 27 autres passent de `unknown` à `closed`.
    * Les 854 autres changent de voie d'accès ouverte. 284 passent de `bronze` à `green` : Unpaywall connaît une copie d'archive absente des copies de la publication. `green` prime sur `bronze` dans le calcul du statut, et `bronze` prime sur `green` dans le verdict d'Unpaywall. Les 570 suivantes passent de `green` ou `bronze` à `gold`, `hybrid` ou `diamond` : Unpaywall connaît une copie sous licence chez l'éditeur. Le modèle de la revue décide ensuite du statut.
    * Hors périmètre, 719 publications sans work OpenAlex passent de `unknown` à `green`.

- Mesure du 2026-11-20, sur les publications à verdict Unpaywall gold ou hybrid : 103 publications `gold` ou `diamond` sont hybrid pour Unpaywall, 416 publications `hybrid` sont gold pour Unpaywall. Parmi ces 416, 334 sont dans une revue hors open access intégral d'après OpenAlex, 56 dans une revue absente d'OpenAlex, 26 parues avant le passage de leur revue à l'open access intégral. Unpaywall classe donc gold sur un autre critère qu'OpenAlex, et applique l'année du passage seulement en partie.
