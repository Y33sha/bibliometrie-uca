# Les liens adresse ↔ site ne s'écrivent pas en base

## Contexte

Une structure de type `site` est un artefact de reconnaissance, non une affiliation. Elle porte les formes de nom géographiques d'un lieu — codes postaux, noms de communes et de campus — pour servir de contexte à la reconnaissance d'autres structures : une forme de nom ambiguë ne vaut que si l'adresse atteste par ailleurs du lieu. Le mécanisme est la colonne `structure_name_forms.requires_context_of`.

La base ne compte qu'un site, « Site clermontois », et il est le premier fournisseur de contexte du référentiel : quarante formes de nom exigent sa présence, devant l'Université Clermont Auvergne (trente-neuf) et les trois organismes nationaux de recherche (douze au total). Il n'est donc pas supprimable — le retirer désarmerait la reconnaissance de ces quarante formes.

La phase `affiliations` ne le distingue en rien des autres structures : elle apparie le texte des adresses aux formes de nom et écrit un lien dans `address_structures` pour chaque appariement, site compris. Le résultat est **58 331 liens vers le site**, deuxième type le plus représenté de la table, tous détectés automatiquement et aucun jamais confirmé ni rejeté — une donnée que rien ne relit, produite par une étape intermédiaire dont seul le résultat importe.

L'API répare ensuite en aval. Le littéral SQL `structure_type != 'site'` est recopié dans quatre requêtes de trois adaptateurs — `queries/api/addresses.py` (deux fois), `queries/api/admin_feedback.py`, `queries/api/persons/detail.py`. Ce sont exactement les quatre lectures qui agrègent toutes les structures d'une adresse ; les autres visent une structure nommée et n'ont donc pas à se garder. La règle « un site n'est pas une affiliation » n'est nommée nulle part, alors que `StructureType.SITE` existe dans le domaine : elle vit en quatre exemplaires, sous forme d'une chaîne de caractères.

## Décisions

**Le lien adresse ↔ site vit dans la phase, pas dans la base.** La résolution d'adresses a besoin de connaître les sites reconnus pour évaluer `requires_context_of`, le temps de son calcul. Ce besoin est interne à l'étape : une fois les structures contextuelles arbitrées, le lien vers le site n'a plus de lecteur. Il est calculé, consommé, et jeté avant l'écriture.

**Le filtrage en aval disparaît, il n'est pas centralisé.** Nommer et mutualiser la condition SQL reviendrait à consolider un contournement que ce chantier supprime. Les quatre occurrences et l'omission de `get_structure_link` s'effacent avec la donnée qui les motive, et l'API cesse d'avoir à connaître l'existence des sites.

**Le stock existant se purge par le mécanisme de la phase.** Les 58 331 liens sont le résidu du comportement corrigé, sans lecteur une fois les filtres retirés. La résolution étant un recalcul complet qui supprime les détections automatiques qu'elle ne retrouve pas, ils tombent d'eux-mêmes au premier passage suivant : aucune migration n'est écrite pour ce qu'une exécution normale du pipeline fait déjà.

## Phasage

### Phase 1 — Cerner les lecteurs

- [x] Le périmètre ne retient aucun site : la matview `source_authorship_structures`, jointe à `perimeter_structures`, ne porte aucune ligne de site. `in_perimeter` est donc hors d'atteinte, et la purge ne déplace pas le périmètre.
- [x] Recensement des lectures. Elles se partagent en deux familles. Celles qui visent une structure nommée — liste et compteurs d'adresses, statistiques et listes de retour de détection, adresses d'un laboratoire, lien d'une adresse à une structure — ne voient un site que si on leur en désigne un, ce qu'aucun appelant ne fait : la structure de travail par défaut est la racine du périmètre. Celles qui agrègent toutes les structures d'une adresse sont les quatre déjà gardées. Aucun compteur ne bouge.
- [x] 3 366 adresses n'ont pour seul rattachement qu'un site : la purge les laisse sans lien. Sans conséquence — n'ayant aucun rattachement à une structure du périmètre, elles en sont déjà hors, et le script de nettoyage des adresses orphelines traite ce cas de la même façon avant comme après.

### Phase 2 — Cesser d'écrire

Le point de branchement est `AddressMatcher.resolve` (`application/pipeline/affiliations/resolve_addresses.py`), et il se prête au filtrage sans rien déplacer. La méthode construit d'abord `structs_matched`, l'ensemble des structures dont une forme apparaît dans l'adresse, puis boucle pour composer son résultat. C'est `structs_matched` qui sert à évaluer `requires_context_of`, jamais le résultat : écarter les sites au moment de composer le résultat laisse donc l'arbitrage du contexte intact. Les structures exclues par `is_excluding` ne sont pas concernées non plus, une forme excluante ne retirant que sa propre structure.

- [ ] `StructureNameForm` porte le type de sa structure ; `load_name_forms` le lit en joignant `structures`, à raison d'une requête par run. Le type voyage avec la donnée de structure plutôt qu'en paramètre d'orchestration : « un site n'est pas une affiliation » est une propriété du modèle, non un réglage de run comme l'est le périmètre.
- [ ] Prédicat nommé dans `domain/structures/`, auprès de `StructureType`, et appelé par `resolve` : la règle cesse d'être une chaîne de caractères recopiée en SQL.
- [ ] Tests : une adresse portant une forme de site et une forme qui dépend de ce contexte produit le lien vers la structure dépendante et aucun lien vers le site. La fabrique `_form` des tests unitaires du matcher porte le champ ajouté.

### Phase 3 — Purger et nettoyer

Le stock se purge de lui-même, sans migration. Chaque run est un recalcul complet, et `delete_obsolete_detections_bulk` supprime les liens détectés et non confirmés absents des appariements de la passe. Les 58 331 liens de site répondent exactement à ce signalement — tous détectés, aucun confirmé — donc ils disparaissent au premier passage de la phase `affiliations` qui suit la phase 2.

- [ ] Vérifier après ce passage que plus aucun lien ne pointe vers une structure de type `site`.
- [ ] Retrait des quatre conditions `structure_type != 'site'` des adaptateurs de lecture, une fois la table assainie.

**Le site reste une structure.** Il n'est pas une structure de recherche — ni existence institutionnelle, ni publications, ni périmètre — mais il emprunte les mêmes circuits qu'elles : formes de nom, appariement, `requires_context_of`. Lui donner son propre référentiel dupliquerait ce mécanisme pour une entité présente en un seul exemplaire. La valeur `site` demeure donc dans `structure_type`, et c'est la persistance de ses liens qui disparaît.

## Questions ouvertes

Aucune.
