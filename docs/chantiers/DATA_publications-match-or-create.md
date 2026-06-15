# Chantier — Publications : retour à match_or_create, corrections a priori, fusion réparatrice

## Contexte

Le modèle en place est **création⇒fusion pur** : chaque `source_publication` orpheline crée une publication canonique sans condition (`create_publications`), puis des passes de fusion publication↔publication dédupliquent par identifiant (DOI, NNT, HAL-ID, PMID) et par métadonnées, gardées par la table `distinct_publications` et par la règle « deux DOI non-nuls différents ⇒ pas de fusion » (`DistinctDoiError`). La contrainte `UNIQUE (lower(doi))` a été retirée à cette occasion.

### Le chantier précédent (création⇒fusion) était une fausse piste

Le pivot vers création⇒fusion répondait à un vrai défaut de l'ancien `match_or_create` : sa passe de rattachement « bulk » hors-périmètre rattachait par DOI **sans** arbitrage ouvrage/chapitre, produisant des fusions abusives (un ouvrage et ses chapitres regroupés sous le DOI du livre). Le diagnostic était bon ; le remède choisi a déplacé le problème plutôt que de le résoudre, et a introduit ses propres coûts :

- **Churn de matérialisation massif.** Sur un rebuild complet : ~326 000 publications créées pour en fusionner ~207 000 immédiatement après (164 809 fusions par DOI, 42 611 par HAL-ID). La phase publications dure ≈ 2 h, dont ~82 min de fusion qui ne sont que de la matérialisation jetée.
- **Treadmill hors-périmètre.** Faute de gate à la création, les orphelines hors-périmètre sont créées, puis purgées en fin de phase authorships (zéro authorship), leur `source_publications.publication_id` repassant à NULL ; au run suivant elles sont recréées puis re-purgées. Chaque cycle paie un `VACUUM ANALYZE` pour contenir le bloat (~58 % des publications purgées, ~118 000 sur un rebuild complet).
- **Règles négatives non-confluentes.** `distinct_publications` matérialise des paires « ne pas fusionner » consultées comme garde. La détection de ces paires est quadratique (une famille de N publications sous un même critère engendre N(N-1)/2 paires), et la garde négative casse la confluence du clustering.

À l'inverse, le défaut originel de `match_or_create` (l'arbitrage ouvrage/chapitre absent de la passe bulk) est soluble **plus proprement** : en transformant les règles de non-fusion en **corrections a priori** des données sources (nuller le DOI erroné porté par un chapitre), le matching redevient positif pur, et l'arbitrage cesse d'être une garde dispersée pour devenir une donnée corrigée en un point. C'est l'objet de ce chantier.

### Cadre théorique

Le problème est un cas de *record linkage incrémental* : un pipeline quotidien qui assigne les nouveaux enregistrements aux entités existantes, tout en réparant a posteriori les regroupements que de nouvelles données révèlent. La littérature (Swoosh / propriétés ICAR, Gruenheid–Dong–Srivastava) éclaire trois points exploitables ici :

- Le matching par **identifiant exact** est ordre-indépendant : `refresh_from_sources` recalcule les métadonnées canoniques comme fonction de l'**ensemble** des sources attachées (premier non-null par priorité de source), pas de l'ordre de fusion. Les fusions **accumulent les clés** (le survivant hérite de l'union des `source_publications`, donc de leurs identifiants), donc une chaîne d'identifiants partagés se referme en une passe par clé, quel que soit l'ordre. Pas besoin d'itérer jusqu'à point fixe.
- Le **seul morceau non-ICAR** du système est constitué des règles **négatives** (`distinct_publications`, `DistinctDoiError`). Les transformer en corrections a priori les fait disparaître du matcher.
- Le matching par **métadonnées** suit la structure *blocking + confirmation* : une clé de blocage (`title_normalized` + `pub_year`) génère des paires candidates, un prédicat pairwise routé par `doc_type` les confirme.

### Note de fait

La phase `normalize` ne rattache **pas** les `source_publications` aux publications existantes (aucun `find_by_doi`/`find_by_hal_id`/lien : tous les normalizers écrivent `publication_id=None`). Les docstrings qui décrivent un tel rattachement (`run_pipeline.phase_normalize`, en-tête de `create_publications`) sont obsolètes et à corriger.

## Décisions

- **Corrections a priori portées par les `source_publications`.** Les corrections de métadonnées (doc_type, journal, oa_status, et désormais DOI nullé) sont calculées et **persistées** en phase `normalize`, de sorte que le matching ex ante porte sur les valeurs corrigées sans recalcul.
- **Correction en place dans les colonnes typées, brut dans un sidecar `raw_metadata` JSONB.** Les colonnes consommées par le matcher (`doc_type`, `journal_id`, `oa_status`, `doi`) portent directement la valeur **corrigée** (effective). Le brut écrasé par une correction est stashé dans `raw_metadata`, **uniquement pour les champs effectivement changés**, au format `{"<champ>": {"raw": <valeur d'origine>, "by": "<règle>"}}` — la valeur d'origine pour la réversibilité, la règle pour l'audit. Choix retenu parce que le matcher (pièce centrale) lit alors des **colonnes nues, indexées, contraintes** : lookup ex ante, group-by ex post et `UNIQUE (lower(doi))` tombent sans index fonctionnel ni colonne générée, et sans invariant « lire l'effective » à faire respecter partout. Reconstruire ce que la source a dit = `COALESCE(raw_metadata->'<champ>'->>'raw', <colonne>)`.
- **Nullage de métadonnée trivial.** Nuller un champ corrigé = colonne `= NULL`, original dans `raw_metadata`. Pas de tri-état (la colonne porte l'effective ; NULL veut dire NULL). La présence d'une clé dans `raw_metadata` est le signal « ce champ a été corrigé ».
- **Idempotence et recompute.** Au re-normalize (cas courant), le normalizer réécrit le **brut** dans la colonne à chaque run ; la correction repart donc toujours du brut frais — idempotence gratuite, pas de double-correction. Le seul chemin sans refetch est l'**édition admin** d'un input éditable (essentiellement `journal_type`) : il faut alors réhydrater le brut depuis `raw_metadata`, réappliquer les règles courantes, re-stasher. Les hooks admin (`update_journal` changeant le `journal_type`, `merge_journals`) doivent donc : (a) recalculer en place les corrections des `source_publications` du journal (réhydrate → réapplique), puis (b) `refresh_from_sources` sur les publications affectées. Obligation bornée mais à câbler explicitement.
- **Règles de non-fusion ⇒ règles de correction.** Les cas de `distinct_publications` (ouvrage/chapitre au même DOI, deux chapitres de titres différents au même DOI, thèse/mémoire vs article partageant une clé) deviennent des corrections : nuller la clé erronée sur le bon côté. `domain/publications/distinct_publications.py` est supprimé et absorbé comme cas particulier de `domain/publications/correction.py`. La table `distinct_publications` et sa passe `mark_distinct` disparaissent du pipeline.
- **Retour à match_or_create.** Le matching ex ante `source_publication` → `publication` est rétabli (cascade par identifiant, puis par métadonnées), avec **gate périmètre en branche no-match** : une source qui matche s'attache quel que soit son périmètre (résolution cross-source d'une source UCA mal renseignée) ; une source qui ne matche rien n'est promue en publication **que** si elle est in-périmètre. Le treadmill et la purge de masse disparaissent.
- **Bascule par revert git, pas réécriture.** Le cluster de la bascule create-all est contigu et auto-contenu (3 commits : `3abeb8ee` → `513046e1` → `feba6e4e`) ; rien de postérieur n'a dérivé son cœur. L'orchestration match_or_create (cascade, gate, ports, tests d'intégration) se **restaure par `git revert`**, surface de conflit limitée à deux fichiers retouchés depuis (`infrastructure/repositories/publication_repository.py`, `application/publications.py`). Le code reverté n'est couplé ni à `v_active_publications` (supprimée) ni à `publications.in_perimeter` (sa requête d'orphelins calcule le périmètre en ligne sur `source_authorships`). L'état post-revert est **transitionnel** — il ramène les gardes négatives (`resolve_doi_conflict`), la passe B bulk aveugle et le match-à-la-création — et ne doit pas tourner en prod avant sa conversion en corrections (Phases 1-2).
- **Fusion réparatrice en aval, conservée.** La fusion publication↔publication reste, dans son rôle de **réparation** (cas résiduel : une nouvelle source ponte deux clusters jusque-là séparés via deux identifiants distincts ; données nouvelles révélant un doublon). Même prédicat que l'assignation, second site de lecture.
- **Retour de `UNIQUE (lower(doi))`.** Une fois les DOI erronés nullés par correction, l'invariant « 1 DOI ⇔ 1 document » est rétabli au niveau schéma. La modélisation des DOI secondaires (`external_ids.related_dois`, jamais clé de fusion) est conservée telle quelle.
- **Forme cible de l'abstraction (orientation, à affiner empiriquement).** Un seul primitif partagé par les deux sites : une **projection** domaine `entité corrigée → ensemble de clés typées`, et — pour le pilier métadonnées — un triplet `(clé de blocage, prefetch des entrées du prédicat, prédicat de confirmation)` déclaré une fois et consommé en deux modes (lookup ex ante, group-by ex post). L'égalité d'identifiant est le cas dégénéré (prefetch vide, confirmation vraie). Aucune logique métier propre à un site. Détail à construire au fil de l'étoffement de la famille de règles métadonnées, pas figé d'avance.

## Phasage

Les phases 1→3 transforment le scaffold restauré en Phase 0, elles ne construisent pas ex nihilo.

### Phase 0 — Revert : restaurer le scaffold match_or_create
- [ ] `git revert feba6e4e 513046e1 3abeb8ee` (ordre chronologique inverse) ; résoudre les conflits sur `infrastructure/repositories/publication_repository.py` et `application/publications.py` (les seuls fichiers du cluster retouchés depuis la bascule).
- [ ] Vérifier la suite verte (les tests d'intégration d'avant-bascule reviennent avec le revert).
- État obtenu **transitionnel** : il ramène `resolve_doi_conflict`, la passe B bulk aveugle et le match-à-la-création. Ne pas lancer en prod avant Phases 1-2. La suite du chantier le transforme.

### Phase 1 — Schéma : corrections persistées + UNIQUE DOI
- [ ] Migration : colonne `raw_metadata` JSONB sur `source_publications` ; la correction écrit l'effective en place dans les colonnes (`doc_type`, `journal_id`, `oa_status`, `doi`) et stashe le brut écrasé dans `raw_metadata` (`{"<champ>": {"raw": …, "by": …}}`), en phase `normalize`.
- [ ] La correction écrit aussi le **DOI corrigé** en place (nullé quand erroné) ; l'original part dans `raw_metadata.doi.raw` pour la réversibilité.
- [ ] Rediriger les hooks admin (`update_journal` changeant le `journal_type`, `merge_journals`) : recompute en place des corrections des `source_publications` du journal (réhydrate le brut depuis `raw_metadata` → réapplique), puis `refresh_from_sources` des publications affectées.
- [ ] Rétablir `UNIQUE (lower(doi))` (migration + `tables.py`), **après** que la passe de correction a nullé les DOI erronés du stock.

### Phase 2 — Non-fusion ⇒ corrections ; retrait des gardes négatives
- [ ] Transformer chaque cas de `distinct_publications` en correction de DOI/clé : ouvrage/chapitre (le chapitre perd le DOI de l'ouvrage), deux chapitres de titres différents au même DOI (les deux perdent le DOI), thèse/mémoire vs article (le côté à corriger, cf. Questions ouvertes).
- [ ] Supprimer `domain/publications/distinct_publications.py` ; loger les cas dans `domain/publications/correction.py`.
- [ ] Retirer la passe `mark_distinct_publications`, la table `distinct_publications` et les gardes `are_distinct` / `DistinctDoiError`, rendues sans objet.
- [ ] Retirer du matcher reverté `resolve_doi_conflict` et la **passe B bulk aveugle** : remplacés par le matching uniforme sur valeurs corrigées (les fusions abusives sont désormais évitées par correction a priori, plus par garde).

### Phase 3 — Matcher positif pur sur valeurs corrigées + unification
- [ ] Pointer la cascade ex ante sur les colonnes **corrigées** (effective), `doc_type` corrigé inclus pour le routage de la dédup métadonnées.
- [ ] Conserver le gate périmètre en branche no-match (restauré en Phase 0 ; à garder tel quel).
- [ ] Fusion réparatrice en aval partageant la projection / le prédicat de confirmation avec l'assignation — zéro logique métier propre à un site.
- [ ] Réévaluer le flag `publications.in_perimeter` : avec le gate, toute publication a ≥1 source in-périmètre, le flag devient constant ; à supprimer si les consommateurs perf (matviews) s'en passent.
- [ ] Corriger les docstrings obsolètes (`normalize`, et l'en-tête hérité du revert).

### Phase 4 — Migration / rerun
- [ ] Rerun complet du stock après bascule ; mesure du nouveau coût de la phase publications.

## Questions ouvertes

- **Côté corrigé pour `thèse/mémoire vs article`** : la clé partagée peut être un DOI ou un HAL-ID ; définir quel côté perd la clé (et selon quel critère de `doc_type`).
- **Routage de la dédup sur un `doc_type` corrigé journal-dépendant** : pour aiguiller la fusion métadonnées (thèse/proceedings) ex ante, la vue de matching doit porter le `doc_type` corrigé, y compris quand la correction dépend du journal (aujourd'hui ces corrections ne s'appliquent qu'au refresh post-création, sur une vue jointe à `journals`). À garantir au moment du match.
- **Qualité du blocking métadonnées** : à mesure que la famille de règles s'étoffe, les clés de blocage pauvres (`title_normalized` générique : « Foreword », actes) engendrent de gros blocs et une confirmation quadratique intra-bloc. Traiter le blocking comme préoccupation de premier ordre (clés composites, normalisation de titre), pas règle par règle. Conseils méthodologiques attendus au fil de l'étoffement.

## Liens

- [archived/2026-06-11_DATA_publications-creation-fusion](archived/2026-06-11_DATA_publications-creation-fusion.md) — le chantier que celui-ci révise : il a corrigé les fusions abusives mais au prix du churn de matérialisation, du treadmill et des gardes négatives non-confluentes.
- [archived/2026-06-11_METIER_fusions-abusives-sources](archived/2026-06-11_METIER_fusions-abusives-sources.md) — origine des cas ouvrage/chapitre et thèse/article, ici reversés en corrections.
- [METIER_relations-publications](METIER_relations-publications.md) — consomme `external_ids.related_dois` (publié ↔ preprint, ouvrage ↔ chapitres, éditions).
- [METIER_doc-types](METIER_doc-types.md) — les mésclassements de `doc_type` relèvent des règles de correction.
