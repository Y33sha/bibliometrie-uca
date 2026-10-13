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

- Une table de redirection, `merge_redirects` : type d'entité, identifiant absorbé, identifiant conservé. Chaque fusion l'écrit, par `record_redirect`.
- Une entité supprimée sans fusion mène à une page introuvable, comme une redirection vers une entité conservée puis supprimée.
- Les fusions antérieures à la table restent sans redirection.
- Une redirection en chaîne (A absorbé par B, puis B par C) se résout à l'écriture : A mène directement à C.
- L'API redirige un identifiant absorbé vers l'identifiant conservé (308, `EntityDetail`), qui centralise aussi le 404 des routes de détail. L'interface publique suit la redirection par un rechargement de la page (`apiDetail`).
- À faire avant la mise en production de l'interface publique.

## Phasage

### Phase 1 — Table et écritures

- [x] Table de redirection, migration Alembic.
- [x] Écriture par les fusions de l'administration (personnes, revues, éditeurs).
- [x] Écriture par les fusions du pipeline (revues, monographies, publications).

### Phase 2 — Lecture

- [x] Redirection dans l'API, pour les pages de détail.
- [x] Suivi de la redirection dans l'interface publique.
