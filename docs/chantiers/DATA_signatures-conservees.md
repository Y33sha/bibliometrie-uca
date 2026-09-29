# Chantier — Signatures conservées à la renormalisation

## Contexte

La normalisation d'une notice supprime ses `source_authorships`, puis les recrée (`clear_source_authorships_for_publication`). Chaque signature change donc d'identifiant à chaque réimport.

L'attribution manuelle d'une signature orpheline pose `person_id` et un épinglage (`confirmed_authorships`). Les deux disparaissent avec la signature, l'épinglage par cascade. Le journal d'audit recense 828 signatures attribuées à la main ; 4 subsistent.

La phase `persons` rattache ensuite les signatures recréées par leur forme de nom. Une forme partagée par plusieurs personnes reste orpheline. « z xu » désigne quatre personnes (Zhilu, Zehua, Zijun et Zhihao Xu) : 6 229 signatures « Z. Xu » sont orphelines.

## Décisions

- La normalisation d'une notice rapproche ses signatures entrantes de celles en base, au lieu de les recréer. Une signature rapprochée garde son identifiant, sa personne et son épinglage.
- Le rapprochement se fait par identité (nom normalisé et identifiants, `identity_id`) :
    - une identité unique dans la notice rapproche la signature entrante de la signature en base ;
    - une identité portée par plusieurs signatures de la notice rapproche les signatures de même position ;
    - une identité différente, ou une identité répétée sans position commune, ne rapproche rien.
- Une signature entrante sans correspondant est insérée. Une signature en base sans correspondant est supprimée, avec son épinglage.
- Une empreinte des champs écrits (position, rôles, auteur correspondant, nom brut, identifiants neutralisés, adresses) évite de réécrire une signature rapprochée inchangée.
- Les empreintes de détection de changement sont calculées en infrastructure (`infrastructure/fingerprint.py`), derrière le port `Fingerprinter`. Changer d'algorithme change tous les `raw_hash` : l'extraction suivante repasse tout le staging en attente.
- La contrainte d'unicité `(source_publication_id, author_position)` devient `DEFERRABLE INITIALLY IMMEDIATE` : vérifiée en fin d'instruction, elle admet une permutation de positions faite en une seule instruction.
- Chaque source isole la partie auteurs de son payload en un bloc, seule entrée de la construction des `AuthorRecord`. Pour HAL, le bloc porte les identifiants déjà extraits du TEI. L'empreinte du bloc est stockée sur la notice (`source_publications.authors_hash`). Une empreinte inchangée laisse les signatures en l'état, sans construction ni rapprochement.
- `run_pipeline --normalize-full` ignore l'empreinte du bloc, pour appliquer une règle de normalisation des auteurs modifiée.

## Phasage

### Phase 1 — Schéma

- [x] Migration : contrainte `source_authorships_pub_pos_key` différable, colonne d'empreinte `content_hash` sur `source_authorships` (`167e4d092`)

### Phase 2 — Synchronisation des signatures

- [x] Domaine : plan de synchronisation pur (rapprochement par identité puis par position ; mises à jour, insertions, suppressions ; empreinte) (`3b9a17bd8`)
- [x] Writer `write_source_authorships` : une instruction par catégorie, adresses réécrites pour les seules signatures modifiées
- [x] Normaliseur des thèses : audit préalable. Il garde la suppression puis réinsertion. Une thèse est renormalisée seulement si son contenu brut change, et ses signatures portent 1 épinglage. Seuls les docteurs figurent dans la file des orphelines.
- [x] Mesure du temps de normalisation, seconde passe sur tout le stock. Notices par seconde : Crossref 16,5 → 37, HAL 25 → 41, OpenAlex 15 → 39.
- [x] Migration : colonne `authors_hash` sur `source_publications`
- [x] Bloc auteurs par source, empreinte du bloc, option `--normalize-full`, empreintes XXH3 128 bits sur une sérialisation `orjson` à clés triées
- [ ] Mesure du temps de normalisation avec l'empreinte du bloc

### Phase 3 — Stock

- [ ] Les attributions perdues aux réimports précédents se refont à la main. Le journal d'audit garde seulement les identifiants des signatures supprimées.
- [ ] Mise à jour de la documentation
