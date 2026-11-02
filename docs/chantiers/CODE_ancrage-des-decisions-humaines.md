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

- [gestion des publications](METIER_gestion-admin-des-publications.md) : interdiction de fusion, veto sur un lien entre contribution source et structure ;
- [audit de la résolution des personnes](DATA_audit-qualite-resolution-personnes.md) : scission d'une contribution, revue des liens d'alignement ;
- [pertinence des sujets](DATA_pertinence-des-sujets.md) : rejet manuel d'un sujet.

## Décisions

- **Une décision humaine s'ancre sur la clé naturelle de sa cible**, jamais sur l'identifiant d'une ligne recalculée par le pipeline. Aucune décision ne disparaît par cascade depuis une ligne recalculée. Une décision sans cible reste en sommeil et s'applique au retour de la cible.
- **Clés naturelles** :
  - enregistrement source : (source, source_id) ;
  - contribution source : enregistrement source, nom normalisé (nom, prénom), et position parmi les contributions sources de même nom dans l'enregistrement source ;
  - personne, structure : identifiant. Une fusion transfère les décisions et redirige l'identifiant.
- **Une adresse décidée échappe à la purge des adresses sans contribution source.** Son identifiant reste donc stable.
- **La normalisation retrouve une contribution source par son nom et ses identifiants, puis par son nom seul, puis par sa position.** Une contribution source garde ainsi son identifiant quand la source ajoute ou retire un identifiant.

## Phasage

### Phase 1 — Correspondance de la normalisation

- [ ] `plan_source_contribution_sync` : nom et identifiants, puis nom seul, puis position.

### Phase 2 — Schéma

- [ ] Migration : `rejected_contributions` ancrée sur (source, source_id, person_id), sans clé étrangère vers `source_records`. Remplie depuis les lignes existantes.
- [ ] Migration : `confirmed_source_contributions` ancrée sur la clé naturelle de la contribution source, sans clé étrangère vers `source_contributions`. Remplie depuis les lignes existantes.

### Phase 3 — Lecture et écriture

- [ ] Résolution des décisions vers les lignes courantes, par un fragment SQL par cible. La résolution des personnes et les fragments de `infrastructure/sql_fragments.py` le lisent.
- [ ] Écritures de l'administration (épinglage, rejet) et fusion des personnes sur les clés naturelles.
- [ ] Purge des adresses sans contribution source : les adresses décidées restent.

### Phase 4 — Documentation

- [ ] Décisions humaines et leurs clés naturelles, dans `docs/donnees/`.

## Questions ouvertes

- **Décisions en sommeil** : les compter dans le journal du pipeline, les lister dans l'administration ?
- **Épinglages perdus** : le journal d'audit donne l'identifiant des contributions sources supprimées, et la publication d'un épinglage unitaire. Une récupération partielle est-elle utile ?
- **Nom corrigé par la source** : l'épinglage ne retrouve plus la contribution source. Repli sur la position seule ?
- **Purge des personnes** : un statut décidé d'identifiant ou de forme de nom épargne-t-il la personne ?
