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

- Mesure du 2026-11-20, sur les publications à verdict Unpaywall gold ou hybrid : 103 publications `gold` ou `diamond` sont hybrid pour Unpaywall, 416 publications `hybrid` sont gold pour Unpaywall. Parmi ces 416, 334 sont dans une revue hors open access intégral d'après OpenAlex, 56 dans une revue absente d'OpenAlex, 26 parues avant le passage de leur revue à l'open access intégral. Unpaywall classe donc gold sur un autre critère qu'OpenAlex, et applique l'année du passage seulement en partie.
