# Chantier — Signatures conservées à la renormalisation

## Contexte

La normalisation d'une notice supprime ses `source_authorships`, puis les recrée (`clear_source_authorships_for_publication`). Chaque signature change donc d'identifiant à chaque réimport.

Deux décisions manuelles disparaissent avec elle :

- **l'attribution d'une signature orpheline**, qui pose seulement `person_id` sur la signature ;
- **l'épinglage** (`confirmed_authorships`), supprimé en cascade avec la signature. Il en reste 4 en base.

La phase `persons` rattache ensuite les signatures recréées par leur forme de nom. Une forme partagée par plusieurs personnes reste orpheline. « z xu » désigne quatre personnes (Zhilu, Zehua, Zijun et Zhihao Xu) : 6 229 signatures « Z. Xu » sont orphelines après réimport, alors qu'elles avaient été attribuées à la main.

## Décisions

- La normalisation d'une notice rapproche ses signatures entrantes de celles en base, au lieu de les recréer. Une signature rapprochée garde son identifiant, sa personne et son épinglage.
- Le rapprochement se fait par identité (nom normalisé et identifiants, `identity_id`) :
    - une identité unique dans la notice rapproche la signature entrante de la signature en base ;
    - une identité portée par plusieurs signatures de la notice rapproche les signatures de même position ;
    - une identité différente, ou une identité répétée sans position commune, ne rapproche rien.
- Une signature entrante sans correspondant est insérée. Une signature en base sans correspondant est supprimée, avec son épinglage.
- Une empreinte des champs écrits (position, rôles, auteur correspondant, nom brut, identifiants neutralisés, adresses) évite de réécrire une signature rapprochée inchangée.
- La contrainte d'unicité `(source_publication_id, author_position)` devient `DEFERRABLE INITIALLY IMMEDIATE` : vérifiée en fin d'instruction, elle admet une permutation de positions faite en une seule instruction.
- L'attribution d'une signature orpheline écrit un épinglage.

## Phasage

### Phase 1 — Schéma

- [x] Migration : contrainte `source_authorships_pub_pos_key` différable, colonne d'empreinte `content_hash` sur `source_authorships` (`167e4d092`)

### Phase 2 — Synchronisation des signatures

- [x] Domaine : plan de synchronisation pur (rapprochement par identité puis par position ; mises à jour, insertions, suppressions ; empreinte) (`3b9a17bd8`)
- [x] Writer `write_source_authorships` : une instruction par catégorie, adresses réécrites pour les seules signatures modifiées
- [ ] Normaliseur des thèses : synchronisation des signatures, dont les non-auteurs à position nulle
- [ ] Mesure du temps de normalisation avant et après, sur une année

### Phase 3 — Épinglage

- [ ] Attribution d'une signature orpheline : écriture dans `confirmed_authorships`

### Phase 4 — Stock

- [ ] Les attributions perdues aux réimports précédents se refont à la main : aucune table ne les a gardées.
- [ ] Mise à jour de la documentation
