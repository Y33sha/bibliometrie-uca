# Chantier — Files d'attente de recalcul

## Contexte

Six colonnes booléennes désignent les lignes qu'une phase du pipeline doit traiter :

| Marqueur | Table | Lignes | Index | Posé par | Lu et effacé par |
|---|---|---|---|---|---|
| `processed` (à faux) | `staging` | 307 715 | 5 | `harvest`, `fetch_*`, réhydratation depuis le raw store | `normalize` |
| `keys_dirty` | `source_records` | 305 104 | 16 | `normalize`, `metadata_correction`, `perimeter_evidence`, propagation aux enregistrements sources d'une même publication | `publications` |
| `contributions_dirty` | `publications` | 76 125 | 14 | `normalize`, `metadata_correction`, `publications`, arbitrage des identifiants | `author_grouping` |
| `countries_dirty` | `source_contributions` | 23 772 388 | 9 | `normalize`, imports ROR et HAL, recalcul des pays | `countries` |
| `countries_dirty` | `addresses` | 428 679 | 7 | résolution des pays | `countries` |
| `candidates_dirty` | `addresses` | 428 679 | 7 | `normalize`, import ROR, saisie manuelle dans l'API | `countries` |

Chaque marqueur a un index partiel, par exemple `WHERE countries_dirty`.

PostgreSQL écrit une nouvelle version de la ligne à chaque `UPDATE`. Il peut éviter d'écrire dans les index si aucune colonne indexée ne change et si la page a la place de la nouvelle version : c'est une mise à jour HOT. Poser ou effacer un marqueur change la condition d'un index partiel, donc la mise à jour n'est jamais HOT. Chaque marquage et chaque effacement réécrit la ligne et ajoute une entrée dans chaque index de la table. Les tables sont remplies à 100 % (`fillfactor` par défaut) : même une mise à jour qui ne touche aucune colonne indexée trouve rarement la place d'être HOT. Seules 1 % des mises à jour de `source_contributions` le sont, et 3 % pour `addresses`.

Mesure du 22 octobre 2026 sur la phase `countries`, avec 5,9 millions de contributions sources marquées : 467 s pour recalculer les pays, 476 s pour effacer les marqueurs.

L'effacement final de la phase `countries` porte sur toutes les lignes marquées, y compris celles marquées après la lecture du périmètre. Une saisie manuelle faite par l'API pendant la phase perd donc son marqueur sans avoir été traitée.

La tâche `author_grouping.attributes` recompose à chaque run les attributs de tous les groupes de contributions sources (`is_corresponding`, `roles`, `perimeter_evidence`) depuis leurs membres. Elle réécrit seulement les groupes qui changent, mais lit les 5,9 millions de groupes et les contributions sources de leurs membres, même quand aucun membre n'a changé.

## Décisions

- **Une file d'attente par marqueur.** Une table étroite du schéma `queues`, nommée avec le suffixe `_queue`, car le graphe des tâches identifie les tables par leur nom sans schéma. Colonnes : `id`, clé primaire ; `seq`, numéro de marquage tiré d'une séquence.
- **Pas de clé étrangère vers la table traitée.** Sa vérification verrouille la ligne référencée à chaque marquage : marquer les 32 millions de contributions sources a réécrit toutes les pages de `source_contributions`. L'identifiant d'une ligne supprimée reste en file. La tâche qui lit la file l'ignore en joignant la table traitée, puis supprime son marquage avec les autres.
- **Marquer, c'est insérer l'identifiant avec un nouveau `seq`.** Pour un identifiant déjà en file, le marquage renouvelle son `seq` (`ON CONFLICT DO UPDATE`).
- **L'effacement porte sur les marquages traités.** La phase relève les couples `(id, seq)` au début, et supprime exactement ceux-là à la fin, par `DELETE`. Un marquage fait pendant la phase change `seq`, donc reste dans la file pour le run suivant. `TRUNCATE` bloquerait les marquages de l'API jusqu'à la fin de la phase.
- **Une seule fonction marque, pour toutes les files** (`infrastructure/db/queues.py`). Chaque point de marquage l'appelle, et le graphe des tâches déclare l'écriture dans la file. Le code qui crée une ligne à traiter l'appelle aussi, à la place des marqueurs à vrai par défaut (`keys_dirty`, `contributions_dirty`, `countries_dirty` des contributions sources, `candidates_dirty`).
- **La migration remplit chaque file depuis le marqueur**, puis supprime la colonne et son index partiel.
- **`staging.processed` reste une colonne.** `normalize` pose ce marqueur dans l'écriture qui vide `raw_data`. Une file n'économiserait aucune écriture.

## Phasage

### Phase 0 — Oneshots joués

- [x] Supprimer les scripts de `interfaces/cli/oneshot/` déjà joués qui posent des marqueurs, avec leurs tests.

### Phase 1 — Pays des contributions sources et des adresses

- [x] Files `source_contribution_countries_queue` et `address_countries_queue`, remplies depuis `countries_dirty`.
- [x] Marquage dans `normalize`, `ror.py`, `hal_structures.py` et `resolution.py`, qui sert aussi à l'API. Le recalcul des pays marque seulement les adresses dont le pays change.
- [x] `create_dirty_scope` lit les files. L'effacement supprime les marquages du périmètre.
- [x] Régénérer `infrastructure/db/schema.sql` une fois la migration appliquée.
- [x] Mesurer la phase `countries`. Run 462 du 23 octobre 2026 : 32 millions de contributions sources en file, dont 10,8 millions à recalculer.

  | Étape | Durée |
  |---|---|
  | Relevé de la file, portée | 425 s |
  | Contributions sources | 292 s |
  | Enregistrements sources | 250 s |
  | Publications | 21 s |
  | Suppression des marquages traités | 145 s |

### Phase 2 — Candidats pays des adresses

- [x] File `address_candidates_queue`, remplie depuis `candidates_dirty`.
- [x] Marquage dans `normalize`, l'import ROR, le dépôt d'adresses de l'API et `redetect_address_countries`. La détection par le texte traite les adresses en file sans les marquer.
- [x] Détection et résolution lisent la file. La résolution immédiate de l'API laisse l'adresse en file : le run suivant refait sa détection.
- [x] Régénérer `infrastructure/db/schema.sql` une fois la migration appliquée.

### Phase 3 — Groupement des auteurs

- [x] File `publication_contributions_queue`, remplie depuis `contributions_dirty`.
- [x] Marquage dans `normalize`, `metadata_correction`, la création et la réconciliation des publications, l'arbitrage des identifiants et la fonction `regroup_identifier_publications` des déclencheurs de l'API. Le `--rebuild` de `author_grouping` remplit la file avec toutes les publications.
- [x] `author_grouping` relève la file au début, et supprime les marquages de chaque lot avant son commit.
- [x] Régénérer `infrastructure/db/schema.sql` une fois la migration appliquée.

### Phase 4 — Réconciliation des publications

- [x] File `source_record_keys_queue`, remplie depuis `keys_dirty`.
- [x] Marquage dans `normalize`, `metadata_correction`, `perimeter_evidence`, la propagation aux enregistrements sources d'une même publication et l'outil de re-matérialisation des clés.
- [x] La réconciliation relève la file au début et supprime les marquages traités à la fin. L'invariant du voisinage à un saut s'exprime avec le marquage.
- [x] Régénérer `infrastructure/db/schema.sql` une fois la migration appliquée.

### Phase 5 — Attributs des groupes

- [x] Journal de la tâche `author_grouping.attributes` : ligne « en cours », puis nombre de groupes réécrits et durée.
- [x] Mesurer la durée de la tâche sur un run complet. Run 461 du 23 octobre 2026 : 3 min 20 s pour la phase `author_grouping`, dont la recomposition de tous les groupes, avec 5,93 millions de groupes réécrits.
- [x] File `source_contribution_group_attributes_queue`, remplie avec tous les groupes.
- [x] Marquage là où un attribut d'un membre change : `perimeter_evidence` (`affiliations`, recalcul ciblé de l'API), `roles` et `is_corresponding` (`normalize`). Le groupement marque les groupes des publications de chaque lot.
- [x] `author_grouping.attributes` relève la file au début et supprime les marquages traités à la fin.
- [x] Régénérer `infrastructure/db/schema.sql` une fois la migration appliquée.
- [x] Mesurer la durée de la tâche après. Premier run avec la file remplie par la migration : 5,93 millions de groupes examinés, 4 557 réécrits en 147 s.
- [ ] Mesurer la durée de la tâche sur un run courant.

### Phase 6 — Mises à jour HOT

- [x] Pour chaque table traitée, relever les colonnes que le pipeline met à jour en masse et vérifier qu'elles sont absentes de tous les index. Candidates : `source_contribution_groups` (attributs, `reference_position`) et `source_contributions` (`countries`, `neutralized_identifiers`, `perimeter_evidence` quand `in_perimeter` ne change pas). Les index GIN sur `countries` interdisent le HOT au recalcul des pays dans `addresses`, `source_records` et `publications`.
- [x] `fillfactor` 90 sur `source_contributions` et `source_contribution_groups` (migration `0f2760ea662f`).
- [ ] Réécrire les deux tables (`VACUUM FULL`) pour libérer de la place dans les pages existantes. `VACUUM FULL` pose un verrou exclusif et double temporairement l'espace disque de la table.
- [ ] Mesurer le taux de mises à jour HOT (`pg_stat_user_tables`) avant et après.

### Phase 7 — Documentation

- [ ] `docs/donnees/08-donnees-derivees.md`, `docs/agregats/addresses.md`, `docs/agregats/source_contributions.md` et les docstrings qui nomment les marqueurs.

## Questions ouvertes

- **Stockage du JSON brut.** Stocker le JSON des sources dans un stockage objet, sans passer par `staging`. Chantier à part.
