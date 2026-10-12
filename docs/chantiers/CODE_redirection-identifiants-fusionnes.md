# Chantier — Redirection des identifiants fusionnés

## Contexte

Une fusion conserve une entité et supprime l'autre. L'identifiant de l'entité absorbée disparaît sans trace. Un lien vers sa page publique mène alors à une page introuvable.

Les fusions concernent cinq entités qui ont une page publique (`/<entité>/[id]`) :

- personnes : fusion par l'administration (`merge_person`) ;
- revues : fusion par l'administration (`merge_journals`) et par `publishers_journals.merge_duplicate_journals` ;
- éditeurs : fusion par l'administration (`merge_publishers`) ;
- monographies : fusion par `publishers_journals.merge_duplicate_monographs` ;
- publications : fusion par `publications.reconcile`, qui conserve la publication ancre et rattache à elle les notices des autres.

## Décisions

- Une table de redirection : type d'entité, identifiant absorbé, identifiant conservé. Chaque fusion l'écrit.
- Une redirection en chaîne (A absorbé par B, puis B par C) se résout à l'écriture : A mène directement à C.
- L'API redirige un identifiant absorbé vers l'identifiant conservé ; l'interface publique suit la redirection.
- À faire avant la mise en production de l'interface publique.

## Phasage

### Phase 1 — Table et écritures

- [ ] Table de redirection, migration Alembic.
- [ ] Écriture par les fusions de l'administration (personnes, revues, éditeurs).
- [ ] Écriture par les fusions du pipeline (revues, monographies, publications).

### Phase 2 — Lecture

- [ ] Redirection dans l'API, pour les pages de détail.
- [ ] Suivi de la redirection dans l'interface publique.

## Questions ouvertes

- Une entité supprimée sans fusion (publication orpheline purgée, revue vide) : page introuvable, ou page qui dit que l'entité a été retirée ?
