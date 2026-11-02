# Chantier — Ancrage des décisions humaines

## Contexte

Le pipeline recalcule les contributions sources, les adresses et les publications. Une décision humaine ancrée sur l'identifiant d'une de ces lignes disparaît avec elle (`ON DELETE CASCADE`).

| Décision | Ancrage | Perte |
|---|---|---|
| Épinglage d'une contribution source sur une personne (`confirmed_source_contributions`) | identifiant de la contribution source | La normalisation recrée une contribution source dont le nom normalisé ou les identifiants changent (`plan_source_contribution_sync`). La suppression de l'enregistrement source emporte aussi l'épinglage. |
| Rejet d'un couple (enregistrement source, personne) (`rejected_contributions`) | identifiant de l'enregistrement source | L'enregistrement source disparaît de sa source, puis revient sous un autre identifiant. |
| Lien entre une adresse et une structure, confirmé ou infirmé (`address_structures.is_confirmed`) | identifiant de l'adresse | La purge supprime une adresse sans contribution source (`delete_orphan_addresses`). Le même texte revient ensuite sous un autre identifiant. |

Trois ancrages tiennent : la fusion manuelle de publications, par (source, source_id) ; les décisions sur une personne, transférées à la fusion et protégées de la purge ; la structure d'un PPN IdRef, par le PPN.

Base locale, 2026-11-02 : le journal d'audit compte 3 289 contributions sources épinglées entre le 2026-09-15 et le 2026-10-09. 1 678 n'existent plus, et leur épinglage a disparu avec elles.

D'autres chantiers prévoient des décisions de même nature :

- [gestion des publications](../METIER_gestion-admin-des-publications.md) : interdiction de fusion, veto sur un lien entre contribution source et structure ;
- [audit de la résolution des personnes](../DATA_audit-qualite-resolution-personnes.md) : scission d'une contribution, revue des liens d'alignement ;
- [pertinence des sujets](../DATA_pertinence-des-sujets.md) : rejet manuel d'un sujet.

## Décisions

- **Une décision humaine vise une ligne à l'identifiant stable.** Le pipeline garde l'identifiant d'une ligne tant qu'elle désigne la même chose.
- **La normalisation reconnaît une contribution source par le nom donné par la source, puis par sa position quand ce nom se répète dans l'enregistrement source.** Une contribution source garde son identifiant quand la source ajoute ou retire un identifiant. Un nom modifié par la source recrée la contribution source, et son épinglage tombe.
- **Une adresse décidée échappe à la purge des adresses sans contribution source.**
- **Un rejet s'ancre sur l'enregistrement source par (source, source_id)**, sans clé étrangère. Le rejet d'un enregistrement source disparu de sa source reste en sommeil et s'applique à son retour.

## Phasage

### Phase 1 — Correspondance de la normalisation

- [x] `plan_source_contribution_sync` : nom donné par la source, puis position (e0287e2c6).
- [x] Contribution source retrouvée avec d'autres identifiants : informations du contributeur réécrites, personne à résoudre de nouveau (e0287e2c6).

### Phase 2 — Rejets

- [x] Migration : `rejected_contributions` ancrée sur (source, source_id, person_id), sans clé étrangère vers `source_records`. Remplie depuis les lignes existantes (fb42e6542).
- [x] Lecture (`infrastructure/sql_fragments.py`), écriture de l'administration et fusion des personnes sur (source, source_id) (fb42e6542).

### Phase 3 — Adresses

- [x] Purge des adresses sans contribution source : les adresses décidées restent (dd0b879af).

### Phase 4 — Documentation

- [x] Normalisation des contributions sources, rejets, purge des adresses (e0287e2c6, fb42e6542, dd0b879af).
