# Chantier — Exécution du pipeline par nœuds

## Contexte

`run.py` exécute les phases dans l'ordre de `PHASE_ORDER` (`pipeline/runtime/phase_order.py`). Chaque phase expose `build()`, dont le code fixe l'ordre de ses étapes.

`pipeline/graph.py` déclare les nœuds du pipeline : une étape, sa phase, ce qu'elle lit et écrit, ses lectures du run précédent. Seuls les tests lisent le graphe. Ils vérifient l'ordre déclaré, pas l'ordre exécuté. Le graphe a donc pu diverger du code : il omettait la recherche de HAL par DOI et la relecture de Crossref, et recopiait des listes de sources que le domaine déclare.

L'ordre des phases est déclaré deux fois : `PHASE_ORDER`, et les groupes des nœuds de `graph.py`. Un test les accorde.

Le journal du terminal suit déjà la structure du graphe : un cadre par phase, des sections (« Éditeurs », « Revues »), une ligne de bilan par étape. Les lignes de bilan de `publishers_journals` correspondent presque une à une à ses dix nœuds.

## Décisions

- **Le journal du terminal garde sa forme** : cadre par phase, titre de section, ligne de bilan par étape, barres de progression.

## Phasage

### Phase 1 — Une seule déclaration

- [ ] `PHASE_ORDER` se déduit des groupes de `graph.py`. Les libellés et la liste des enrichissements deviennent des attributs de phase dans `graph.py`. Suppression de `phase_order.py`.
- [x] Les nœuds par source du graphe lisent les listes du domaine : `HARVESTED_SOURCES`, `ALL_SOURCES`, `DOI_SEARCHABLE_SOURCES`, `SOURCE_PRIORITY`.

### Phase 2 — Inventaire

- [ ] Pour chaque phase, confronter les étapes de `build()` aux nœuds de `graph.py` : nœuds absents, étapes non déclarées, ordre.
- [ ] Pour chaque nœud, la section et la ligne de journal qui lui correspondent.

### Phase 3 — Exécution par nœuds

- [ ] Chaque nœud désigne sa fonction. `run.py` exécute les nœuds dans l'ordre du graphe. Il affiche le cadre quand le groupe change, le titre de section quand la section change, puis le bilan du nœud.
- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Granularité de `--only` et `--from` : groupe, nœud, ou les deux.
- Métriques et signaux enregistrés dans `pipeline_phase_executions` : par nœud ou par groupe. Le ruban de l'interface lit cette table.
- Conditions d'exécution d'un nœud (options `--rebuild-*`, source non configurée, rien à faire) : déclarées dans le graphe ou gardées dans la fonction du nœud.
- Nœuds qui tournent en parallèle dans leur phase (`extract.<source>`, `fetch_missing.doi.<source>`) : comment le graphe le déclare.
