# Chantier — Sidecar `rejected_authorships` (extraire `authorships.excluded`)

Commencé et terminé le 2026-06-01

Sous-chantier de [`DATA_donnees-derivees`](DATA_donnees-derivees.md) (Phase 2). Prérequis de la conversion de `authorships` en `MATERIALIZED VIEW` : dissoudre le dernier îlot d'état natif de la table.

## Contexte

`authorships.excluded` porte le **rejet canonique** d'une contribution : « cette personne n'est PAS l'auteur de cette publication ». Posé par la croix one-way de la page personne (`PATCH /api/authorships/{id}/exclude` → `exclude_authorship`), avec confirmation « ne sera pas recréé automatiquement ». Pas de restauration dans l'UI.

Aujourd'hui `exclude_authorship` fait **deux** choses : (1) `UPDATE authorships SET excluded = TRUE`, (2) nulle le `person_id` des `source_authorships` de la paire (pour que le rebuild ne recrée pas le lien). Cette double écriture rend la persistance **fragile** :

- En mode `full`, `purge_authorships` fait `DELETE` de toute la table : le row `excluded` disparaît. Le rejet ne survit alors que par le détachement source (person_id nullé).
- Mais ce détachement est lui-même **réversible** : au run suivant, la cascade de matching personnes (`decide_person_match`) peut ré-attacher le `person_id` à la `source_authorship` (même ORCID / même nom) → `insert_missing_authorships` recrée la paire → **le rejet saute**.

Donc ni la colonne ni le détachement ne garantissent la durabilité. Un store **univoque** `rejected_authorships(publication_id, person_id)`, lu par tout site qui crée une `authorships`, est la seule façon robuste de figer le rejet à travers les rebuilds.

**Volumétrie prod** (DB `bibliometrie`, 110 313 authorships) : `excluded = 0`, `source_manual = 0`. La feature est câblée mais jamais exercée → migration sans backfill réel (on backfille quand même par principe d'idempotence). `source_manual` est vestigial (0 prod, aucune query, jamais écrit `TRUE` hors un test) → à dropper dans le même mouvement.

## Décisions

### Modèle : skip-at-build, pas tombstone

Une paire rejetée n'a **aucun** row `authorships` (le row est supprimé à l'exclusion, jamais recréé). Conséquence : pas de colonne `excluded`, et **les ~20 filtres `NOT a.excluded` disparaissent purement** (les rows filtrés n'existent plus) — au lieu de devenir des anti-joins à la lecture. Un seul anti-join, à chaque site qui **insère** dans `authorships`, suffit à maintenir l'invariant « une paire du sidecar n'a jamais de row ».

Alternative écartée : garder un row `excluded=TRUE` (tombstone) et anti-joindre le sidecar dans chaque query de lecture. Plus de points de contact, moins DRY.

### Table

```sql
CREATE TABLE rejected_authorships (
    publication_id integer NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    person_id      integer NOT NULL REFERENCES persons(id)      ON DELETE CASCADE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (publication_id, person_id)
);
```

Pas de colonne « raison » / « quelle info source est fausse » : **anti-suringénierie**, hors scope (futur chantier seulement si besoin réel).

### `exclude_authorship` réécrit

1. Lit `(publication_id, person_id)` du row.
2. `INSERT INTO rejected_authorships ... ON CONFLICT DO NOTHING`.
3. `DELETE FROM authorships WHERE id = :id` — les FK nettoient `authorship_structures` (CASCADE) et `source_authorships.authorship_id` (SET NULL).
4. **Ne touche plus au `person_id` des sources** : la vérité source est préservée, le rejet vit dans le sidecar.

### Détachement source abandonné

Aujourd'hui l'exclusion nulle le `person_id` des `source_authorships` ; le sidecar rend ce détachement à la fois inutile (l'anti-join suffit) et il était de toute façon non durable. On l'abandonne. Effet de bord assumé : une paire rejetée garde son `person_id` côté source, donc `name_forms` continue d'attribuer la forme de nom à la personne. C'est acceptable — le rejet porte sur *(personne, publication)*, pas sur *(personne, nom)*, et la forme existe de toute façon via les autres publis de la personne. Le nettoyage des formes de nom héritées d'un matching erroné est une **vulnérabilité plus vaste** (déjà présente, ex. identifiant rejeté ne purge pas ses formes), traitée hors de ce chantier ; le palliatif actuel (détacher les `source_authorships` erronées depuis `admin/persons`) reste suffisant.

### Fusion de personnes : transfert du rejet

Une fusion signifie que deux `persons` sont la **même** identité : ce qui est vrai de l'une l'est de l'autre. Un rejet posé sur la personne absorbée doit donc **migrer** vers l'absorbante. `merge_into` gagne le même motif dédup-puis-transfert que les autres tables FK : `DELETE` des rows source qui entreraient en conflit de PK avec la cible, puis `UPDATE rejected_authorships SET person_id = target WHERE person_id = source`.

### Anti-join à chaque INSERT INTO `authorships`

Sites recensés : `insert_missing_authorships` (build principal) et le chemin d'assignation d'orphelins (`create_authorships_from_sources` / `link_*`). Chacun gagne un `AND NOT EXISTS (SELECT 1 FROM rejected_authorships rj WHERE rj.publication_id = ... AND rj.person_id = ...)`.

### Retraits

- Colonne `authorships.excluded` + tous les `NOT a.excluded` (filters, facets, list, detail, stats/labs, *_duplicates, observability).
- Colonne `authorships.source_manual` (+ champ domaine `Authorship.source_manual`, projection repo, tests).

## Phasage

Livré en un commit (`84b2dc83`, migration `f3b6d9c1a8e2`).

- [x] **Migration + schéma + domaine** : créer `rejected_authorships` ; backfill depuis `authorships WHERE excluded AND person_id IS NOT NULL` (0 row en prod, idempotent) ; `DROP COLUMN excluded`, `DROP COLUMN source_manual`. `tables.py`, `domain/publications/authorship.py`, projection `_AuthorshipRow`.
- [x] **Écriture** : `exclude_authorship` → sidecar + DELETE row. Port/repo : `mark_authorship_excluded` → `reject_authorship(publication_id, person_id)` + `delete_authorship` ; anti-join sidecar dans les 3 sites d'INSERT ; transfert du rejet dans `merge_into`.
- [x] **Lecture** : retrait des `NOT a.excluded`.
- [x] **Tests + doc** (08-authorships, 05-authorships-et-sources, 10-resume ; roadmap parent cochée).

## Questions ouvertes

- **Restauration (un-reject)**. La feature est one-way aujourd'hui. Le sidecar la rendrait triviale (`DELETE` du sidecar + rebuild de la paire), mais ce n'est pas demandé → **hors scope** sauf besoin.
