# Chantier — Suppression des `conn`/`cur` fossiles

Commencé le 2026-05-11.

## Contexte

Dette héritée du chantier SQLAlchemy : nombreuses fonctions de
`application/` (et probablement `infrastructure/sources/`,
`interfaces/api/routers/`, tests) déclarent un argument
`conn: Connection` ou `cur: Connection` qu'elles n'utilisent **pas**.
Vestige du pattern psycopg où le curseur servait à `cur.execute(...)`
directement. Avec `repo` qui encapsule la connexion, l'argument est
devenu un fossile sur les signatures.

Audit initial dans `application/persons.py` : 13 fonctions sur 16
avec un argument fossile. Présomption d'une situation similaire dans
les autres modules `application/*`.

## Cascade

Beaucoup de `conn`/`cur` *utilisés* le sont uniquement pour les
transmettre à une autre fonction qui ne l'utilise pas non plus. En
supprimant les feuilles, on libère les remontées. Le chantier est
itératif : sweep, propage, re-sweep.

## Stratégie

1. **Audit initial** : pour chaque fonction de `application/*`,
   identifier si `conn`/`cur` est référencé dans le corps.
2. **Sweep itératif** :
   - Supprimer les arguments des feuilles (fonctions qui n'utilisent
     jamais `conn`/`cur` dans leur corps).
   - Adapter tous les call sites (qui ne passent plus l'argument).
   - Re-auditer : certains callers deviennent feuilles à leur tour.
   - Itérer.
3. **Tests adaptés** au passage (les tests appellent souvent les
   use cases avec un `conn`).
4. **Validation continue** : mypy + tests à chaque sweep.

## Hors scope

- Renommage `cur` → `conn` quand le variable garde un usage légitime.
  Reporté à un chantier dédié si nécessaire.
- Refactor de l'usage interne (continuer à passer `conn` aux repos
  qui en ont besoin par leur `__init__`).
- `infrastructure/sources/*` extracteurs API : à voir en queue, le
  pattern y est probablement différent (commits batch).

## Phasage

### Phase 1 — Audit complet

- [ ] Lister toutes les fonctions de `application/`, `interfaces/api/`,
  `tests/integration/application/` qui déclarent `conn` ou `cur` mais
  ne l'utilisent jamais dans leur corps.

### Phase 2 — Sweep itératif

- [ ] Supprimer les arguments fossiles, adapter les call sites
  (probablement plusieurs commits intermédiaires).

### Phase 3 — Validation finale

- [ ] mypy + tests + suite complète.
