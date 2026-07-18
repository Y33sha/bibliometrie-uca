# Les liens adresse ↔ site ne s'écrivent pas en base

## Contexte

Une structure de type `site` est un artefact de reconnaissance, non une affiliation. Elle porte les formes de nom géographiques d'un lieu — codes postaux, noms de communes et de campus — pour servir de contexte à la reconnaissance d'autres structures : une forme de nom ambiguë ne vaut que si l'adresse atteste par ailleurs du lieu. Le mécanisme est la colonne `structure_name_forms.requires_context_of`.

La base ne compte qu'un site, « Site clermontois », et il est le premier fournisseur de contexte du référentiel : quarante formes de nom exigent sa présence, devant l'Université Clermont Auvergne (trente-neuf) et les trois organismes nationaux de recherche (douze au total). Il n'est donc pas supprimable — le retirer désarmerait la reconnaissance de ces quarante formes.

La phase `affiliations` ne le distingue en rien des autres structures : elle apparie le texte des adresses aux formes de nom et écrit un lien dans `address_structures` pour chaque appariement, site compris. Le résultat est **58 331 liens vers le site**, deuxième type le plus représenté de la table, tous détectés automatiquement et aucun jamais confirmé ni rejeté — une donnée que rien ne relit, produite par une étape intermédiaire dont seul le résultat importe.

L'API répare ensuite en aval. Le littéral SQL `structure_type != 'site'` est recopié dans quatre requêtes de trois adaptateurs — `queries/api/addresses.py` (deux fois), `queries/api/admin_feedback.py`, `queries/api/persons/detail.py`. Ce sont exactement les quatre lectures qui agrègent toutes les structures d'une adresse ; les autres visent une structure nommée et n'ont donc pas à se garder. La règle « un site n'est pas une affiliation » n'est nommée nulle part, alors que `StructureType.SITE` existe dans le domaine : elle vit en quatre exemplaires, sous forme d'une chaîne de caractères.

## Décisions

**Le lien adresse ↔ site vit dans la phase, pas dans la base.** La résolution d'adresses a besoin de connaître les sites reconnus pour évaluer `requires_context_of`, le temps de son calcul. Ce besoin est interne à l'étape : une fois les structures contextuelles arbitrées, le lien vers le site n'a plus de lecteur. Il est calculé, consommé, et jeté avant l'écriture.

**Le filtrage en aval disparaît, il n'est pas centralisé.** Nommer et mutualiser la condition SQL reviendrait à consolider un contournement que ce chantier supprime. Les quatre occurrences et l'omission de `get_structure_link` s'effacent avec la donnée qui les motive, et l'API cesse d'avoir à connaître l'existence des sites.

**Le stock existant se purge.** Les 58 331 liens sont le résidu du comportement corrigé, sans lecteur une fois les filtres retirés. Ils sont supprimés par migration, et non laissés en place : les conserver ferait dépendre l'exactitude des lectures de filtres qu'on vient d'enlever.

## Phasage

### Phase 1 — Cerner les lecteurs

- [x] Le périmètre ne retient aucun site : la matview `source_authorship_structures`, jointe à `perimeter_structures`, ne porte aucune ligne de site. `in_perimeter` est donc hors d'atteinte, et la purge ne déplace pas le périmètre.
- [x] Recensement des lectures. Elles se partagent en deux familles. Celles qui visent une structure nommée — liste et compteurs d'adresses, statistiques et listes de retour de détection, adresses d'un laboratoire, lien d'une adresse à une structure — ne voient un site que si on leur en désigne un, ce qu'aucun appelant ne fait : la structure de travail par défaut est la racine du périmètre. Celles qui agrègent toutes les structures d'une adresse sont les quatre déjà gardées. Aucun compteur ne bouge.
- [x] Effet de bord relevé : 3 366 adresses n'ont pour seul rattachement qu'un site. La purge les laisse sans aucun lien, ce qui les rend éligibles à `interfaces/cli/maintenance/cleanup_publications_out_of_window.py`, qui supprime les adresses sans signature ni rattachement. Correct — une adresse que plus rien ne relie n'a pas de raison de subsister — mais à constater après purge plutôt qu'à découvrir au prochain passage du script.

### Phase 2 — Cesser d'écrire

- [ ] La résolution d'adresses garde les appariements de sites pour l'évaluation de `requires_context_of`, et ne les retient pas parmi les liens à persister. La règle vit dans le domaine, auprès de `StructureType`, et non en SQL.
- [ ] Tests : une adresse dont le texte porte une forme de site et une forme dépendante de son contexte produit le lien attendu vers la structure dépendante, et aucun lien vers le site.

### Phase 3 — Purger et nettoyer

- [ ] Migration supprimant les liens `address_structures` dont la structure est de type `site`.
- [ ] Retrait des quatre conditions `structure_type != 'site'` des adaptateurs de lecture.
- [ ] Contrôle après purge : les adresses devenues sans rattachement sont celles attendues, et leur suppression éventuelle passe par le script de nettoyage existant, non par ce chantier.

**Le site reste une structure.** Il n'est pas une structure de recherche — ni existence institutionnelle, ni publications, ni périmètre — mais il emprunte les mêmes circuits qu'elles : formes de nom, appariement, `requires_context_of`. Lui donner son propre référentiel dupliquerait ce mécanisme pour une entité présente en un seul exemplaire. La valeur `site` demeure donc dans `structure_type`, et c'est la persistance de ses liens qui disparaît.

## Questions ouvertes

Aucune.
