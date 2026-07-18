# Les liens adresse ↔ site ne s'écrivent pas en base

## Contexte

Une structure de type `site` est un artefact de reconnaissance, non une affiliation. Elle porte les formes de nom géographiques d'un lieu — codes postaux, noms de communes et de campus — pour servir de contexte à la reconnaissance d'autres structures : une forme de nom ambiguë ne vaut que si l'adresse atteste par ailleurs du lieu. Le mécanisme est la colonne `structure_name_forms.requires_context_of`.

La base ne compte qu'un site, « Site clermontois », et il est le premier fournisseur de contexte du référentiel : quarante formes de nom exigent sa présence, devant l'Université Clermont Auvergne (trente-neuf) et les trois organismes nationaux de recherche (douze au total). Il n'est donc pas supprimable — le retirer désarmerait la reconnaissance de ces quarante formes.

La phase `affiliations` ne le distingue en rien des autres structures : elle apparie le texte des adresses aux formes de nom et écrit un lien dans `address_structures` pour chaque appariement, site compris. Le résultat est **58 331 liens vers le site**, deuxième type le plus représenté de la table, tous détectés automatiquement et aucun jamais confirmé ni rejeté — une donnée que rien ne relit, produite par une étape intermédiaire dont seul le résultat importe.

L'API répare ensuite en aval, et mal. Le littéral SQL `structure_type != 'site'` est recopié dans quatre requêtes de trois adaptateurs — `queries/api/addresses.py` (deux fois), `queries/api/admin_feedback.py`, `queries/api/persons/detail.py` — et manque à `get_structure_link`, qui lit pourtant le même lien que ses voisines. Une adresse peut donc rendre un lien vers une structure absente de sa propre liste de structures. La règle « un site n'est pas une affiliation » n'est nommée nulle part, alors que `StructureType.SITE` existe dans le domaine.

## Décisions

**Le lien adresse ↔ site vit dans la phase, pas dans la base.** La résolution d'adresses a besoin de connaître les sites reconnus pour évaluer `requires_context_of`, le temps de son calcul. Ce besoin est interne à l'étape : une fois les structures contextuelles arbitrées, le lien vers le site n'a plus de lecteur. Il est calculé, consommé, et jeté avant l'écriture.

**Le filtrage en aval disparaît, il n'est pas centralisé.** Nommer et mutualiser la condition SQL reviendrait à consolider un contournement que ce chantier supprime. Les quatre occurrences et l'omission de `get_structure_link` s'effacent avec la donnée qui les motive, et l'API cesse d'avoir à connaître l'existence des sites.

**Le stock existant se purge.** Les 58 331 liens sont le résidu du comportement corrigé, sans lecteur une fois les filtres retirés. Ils sont supprimés par migration, et non laissés en place : les conserver ferait dépendre l'exactitude des lectures de filtres qu'on vient d'enlever.

## Phasage

### Phase 1 — Cerner les lecteurs

- [ ] Recenser tout ce qui lit `address_structures` sans exclure les sites : au-delà des quatre requêtes d'API connues, le pipeline lui-même (`in_perimeter`, matview `source_authorship_structures`) et les CLI. Un lecteur qui compterait aujourd'hui les liens site verrait ses résultats changer.
- [ ] Vérifier que `perimeter_structures` ne retient aucun site, faute de quoi la suppression des liens déplacerait le périmètre.

### Phase 2 — Cesser d'écrire

- [ ] La résolution d'adresses garde les appariements de sites pour l'évaluation de `requires_context_of`, et ne les retient pas parmi les liens à persister. La règle vit dans le domaine, auprès de `StructureType`, et non en SQL.
- [ ] Tests : une adresse dont le texte porte une forme de site et une forme dépendante de son contexte produit le lien attendu vers la structure dépendante, et aucun lien vers le site.

### Phase 3 — Purger et nettoyer

- [ ] Migration supprimant les liens `address_structures` dont la structure est de type `site`.
- [ ] Retrait des quatre conditions `structure_type != 'site'` des adaptateurs de lecture.
- [ ] Contrôle : `get_structure_link` et `get_address_structures` rendent des vues cohérentes d'une même adresse, ce qui n'était pas le cas.

## Questions ouvertes

- **Le rangement des sites dans le référentiel des structures.** Un site n'est pas une structure de recherche : il partage la table pour bénéficier du moteur de formes de nom, mais n'a ni existence institutionnelle, ni publications, ni périmètre. Les lectures d'API qui l'excluent le disent déjà, chacune dans son coin. Une fois les liens supprimés, reste à savoir si le type `site` demeure une valeur de `structure_type` ou si le contexte géographique mérite son propre référentiel. Question de modélisation, indépendante de ce chantier et à instruire après lui.
