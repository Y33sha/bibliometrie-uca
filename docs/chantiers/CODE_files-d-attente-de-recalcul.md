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

## Décisions

- **Une file d'attente par marqueur.** Une table étroite, avec l'identifiant de la ligne à traiter pour seule colonne et clé primaire, et une clé étrangère `ON DELETE CASCADE` vers la table traitée. Marquer, c'est insérer l'identifiant (`ON CONFLICT DO NOTHING`). Traiter, c'est lire la file. Effacer, c'est supprimer de la file les identifiants traités. La table traitée n'est plus réécrite pour marquer ni pour effacer, et perd son index partiel.
- **L'effacement porte sur les identifiants traités.** La phase relève les identifiants de la file au début, et supprime exactement ceux-là à la fin. Un identifiant inséré pendant la phase reste dans la file pour le run suivant.
- **Chaque création de ligne à traiter insère dans la file.** Les marqueurs à vrai par défaut (`keys_dirty`, `contributions_dirty`, `countries_dirty` des contributions sources, `candidates_dirty`) se remplacent par une insertion explicite dans le code qui crée la ligne.
- **La migration remplit chaque file depuis le marqueur**, puis supprime la colonne et son index partiel. Aucun traitement en attente n'est perdu.

## Phasage

### Phase 1 — Pays des contributions sources et des adresses

- [ ] Files `source_contribution_countries_queue` et `address_countries_queue`, remplies depuis `countries_dirty`.
- [ ] Marquage dans `normalize`, `ror.py`, `hal_structures.py`, `resolution.py`, le recalcul des pays et le recalcul ciblé de l'API.
- [ ] `create_dirty_scope` lit les files. L'effacement supprime les identifiants du périmètre.
- [ ] Mesurer la phase `countries` sur le même volume qu'au 22 octobre 2026.

### Phase 2 — Candidats pays des adresses

- [ ] File `address_candidates_queue`, remplie depuis `candidates_dirty`.
- [ ] Marquage dans `normalize`, l'import ROR, le dépôt d'adresses de l'API et `redetect_address_countries`.
- [ ] Détection et résolution lisent la file.

### Phase 3 — Groupement des auteurs

- [ ] File `publication_contributions_queue`, remplie depuis `contributions_dirty`.
- [ ] Marquage dans `normalize`, `metadata_correction`, la réconciliation des publications et l'arbitrage des identifiants. Le `--rebuild` de `author_grouping` remplit la file avec toutes les publications.
- [ ] `author_grouping` lit la file par lots, et supprime chaque lot traité.

### Phase 4 — Réconciliation des publications

- [ ] File `source_record_keys_queue`, remplie depuis `keys_dirty`.
- [ ] Marquage dans `normalize`, `metadata_correction`, `perimeter_evidence`, la propagation aux enregistrements sources d'une même publication et l'outil de re-matérialisation des clés.
- [ ] La réconciliation lit la file. Reformuler dans `domain/publications/reconciliation.py` et `pipeline/transformation/publications/reconciliation.py` l'invariant du voisinage à un saut, aujourd'hui exprimé avec le marqueur.

### Phase 5 — Mises à jour HOT

- [ ] Pour chaque table traitée, relever les colonnes que le pipeline met à jour en masse et vérifier qu'elles sont absentes de tous les index.
- [ ] Fixer un `fillfactor` inférieur à 100 sur les tables où ces mises à jour peuvent devenir HOT, puis réécrire la table (`VACUUM FULL`) pour libérer de la place dans les pages existantes.
- [ ] Mesurer le taux de mises à jour HOT (`pg_stat_user_tables`) avant et après.

### Phase 6 — Documentation

- [ ] `docs/donnees/08-donnees-derivees.md`, `docs/agregats/addresses.md`, `docs/agregats/source_contributions.md` et les docstrings qui nomment les marqueurs.

## Questions ouvertes

- **`staging.processed`.** `normalize` réécrit déjà la ligne en vidant `raw_data` au moment où il pose le marqueur : la file ne supprime pas cette réécriture. Elle supprime l'index partiel et aligne `staging` sur les autres tables. L'`UPSERT` de `staging` pose aussi le marqueur selon `raw_hash`, dans la même instruction : il faudrait l'insertion dans la file à côté. Inclure `staging`, ou le laisser hors du chantier ?
- **Insertion explicite ou trigger.** Un trigger `AFTER INSERT` garantit qu'aucune création n'oublie la file, mais déplace dans la base une règle que le code ne montre plus. L'insertion explicite est visible et testable, mais dépend de la discipline de chaque point de création.
- **`TRUNCATE` ou `DELETE`.** `TRUNCATE` vide une file instantanément, mais pose un verrou exclusif et efface aussi les identifiants insérés pendant la phase. Il convient seulement à une file que seul le pipeline remplit, et que la phase traite en entier.
