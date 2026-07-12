# Phase personnes — lisibilité et refonte

## Contexte

La phase `persons` (`application/pipeline/persons/`) enchaîne enforce → reset → match → create → populate → purge sur une transaction unique. Une relecture à froid en outsider fait ressortir plusieurs points qui feraient tiquer un nouveau venu, dont certains lourds concentrés dans `cascade.py`. Cette fiche les regroupe pour un traitement dédié, distinct de la passe de lisibilité générale (`CODE_lisibilite.md`).

## Décisions

À trancher au fil du chantier ; le Phasage ci-dessous liste les pistes, pas des choix arrêtés.

## Phasage

### cascade.py — désengorger

- [ ] Quatre responsabilités dans un fichier (~480 lignes) : chargement de données (`get_all_unlinked_authorships`, `load_linked_authorships_by_pub`, `_max_authors_per_pub`), état de passe (`_Cascade` et ses 7 index préchargés), les deux passes (`match`, `create`), assemblage des métriques (`build_metrics`). À découper.
- [ ] `match` et `create` sont quasi-dupliqués : même squelette (instancier `_Cascade`, boucler, `decide_*`, `apply_*`) ; seuls la méthode de décision (`decide_full` vs `decide_cross_and_name`) et le sort de l'action `create` (`pass` différé chez `match`, `apply_create` chez `create`) diffèrent. Factoriser une passe paramétrée. Le double `_Cascade` (donc le double rechargement des 7 index par run) est voulu — `create` doit voir ce que `match` a posé — ; c'est le squelette de boucle qui est du copier-coller.
- [ ] `_max_authors_per_pub` : suringénierie. Agrège le nombre d'auteurs par publication (max entre sources) pour gater le matching cross-source des méga-papers, avec un seuil magique (`50`, « proxy arbitraire » de l'aveu du docstring). Le compte d'auteurs est une propriété de chaque `source_publication` : le porter sur l'authorship et gater le seul signal cross-source dessus suffit (les signaux identifiants restent fiables quelle que soit la taille du papier). Une publi mixte (SP au-dessus ET en dessous du seuil) n'utilise alors que ses SP éligibles — comportement attendu, sans agrégat pré-calculé. Détail à respecter : filtrer aussi les SP méga du pool de candidats (une petite SP ne doit pas matcher contre les positions d'une SP méga). Résultat : agrégat + nombre magique remplacés par un prédicat par-authorship.

### Boundary services

- [ ] `EnrichedAuthorship` (NamedTuple typé, 15 champs) est reconverti en `dict` via `_asdict()` parce que `link_to_person`/`add_identifiers` (`application.services.persons`) consomment des dicts. On construit un tuple typé pour le désassembler juste après. Aligner l'API services sur le type (ou l'inverse) pour lever l'impédance.

### Docstrings

- [ ] Docstrings-fleuves : `cascade.py` ouvre sur ~37 lignes de module ; `reset`/`purge`/`resolve_identifier_transfers`/`populate_person_name_forms` ont 14–24 lignes chacun. Le volume porte surtout du rationale de conception (seuils, double-fetch, gardes) qui narre ce que la logique déléguée à `domain/persons/matching.py` fait. Une fois `cascade.py` découpé et la logique clarifiée, resserrer — ce qui reste du rationale peut migrer vers une note d'architecture.
- [ ] `phase.py` : `mono-transaction` sur-souligné. Le docstring martèle le *quoi* (« une seule transaction ») sans le *pourquoi* — l'atomicité du `reset` destructif : la remise à NULL des attributions dérivées et sa reconstruction (`match`/`create`) doivent committer ensemble, sinon un crash en cours de phase laisse des signatures détachées jusqu'au run suivant. Énoncer ce pourquoi et découpler de « ordre-indépendante », qui est une propriété de l'algorithme (recompute complet + consensus + lectures d'agrégat), pas de la transaction.

## Questions ouvertes

- `enforce` est numéroté comme l'étape 1 de la phase mais reste un appel repo inline dans `phase.py` (`authorship_repo.enforce_confirmed_authorships()`), là où les cinq autres étapes sont des modules. Motif récurrent dans d'autres phases : convention « étape = module » à trancher globalement, plutôt que dans cette seule fiche.
