# Chantier — Le SQL métier partagé hors d'`infrastructure/db`

## Contexte

`infrastructure/db/` est un dossier bas niveau : connexion et transactions (`engine.py`, `transaction.py`), garde-fous d'exécution (`dml_guard.py`, `read_only_guard.py`), types et lecture des relevés (`jsonb.py`, `rows.py`, `scalars.py`), description du schéma (`tables.py`).

Trois modules y contiennent du SQL métier, partagé entre les repositories ou read models de l'API et le pipeline :

- `sql_fragments.py` : utilitaires génériques (`in_clause`, `case_priority`) et prédicats métier (identifiant neutralisé, paires rejetées, appartenance d'une authorship au périmètre, ISSN actifs, détenteurs d'une forme de nom). 27 modules l'importent.
- `journal_issns.py` : lecture des ISSN d'une revue sous forme de `JournalIssn`.
- `merge_steps.py` : mécanique des fusions de personnes, d'éditeurs et de revues, et condition « sans décision humaine ».

## Décisions

## Phasage

### Phase 1 — Inventaire

- [ ] Classer chaque fragment de `sql_fragments.py` : utilitaire générique, ou prédicat métier, avec son domaine et ses utilisateurs.

## Questions ouvertes

- Destination du SQL métier partagé : un paquet dédié découpé par domaine (`infrastructure/sql/`), ou du SQL propre à chaque côté avec les règles dans `domain/`. Les prédicats de lecture (paires rejetées, périmètre) encodent des règles qu'une duplication ferait diverger.
- Liste commune des colonnes de chaque donnée d'une personne, que lisent la fusion des personnes et la purge de la phase `persons` (`person_without_decision_sql`).
