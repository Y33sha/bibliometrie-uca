# Chantier — Normalisation du schéma `person_name_forms`

Schéma actuel : `person_name_forms(name_form, person_ids[], sources[])`
— deux arrays parallèles non-corrélés. Conséquence : pour une forme
liée à plusieurs personnes via plusieurs sources, on ne sait pas
quel `(person_id, source)` est responsable de quoi.

Exemple problématique : forme `"j dupont"` reliée à person 1 (Jérôme
Dupont) via `persons` et à person 2 (Jeanne Dupont-Martin) via
`openalex` — finit avec `person_ids=[1,2], sources=['persons','openalex']`,
zéro moyen de tracer 1↔persons et 2↔openalex sans recalculer.

C'est cette faiblesse qui justifie la **recalculation systématique
batch** dans `populate_person_name_forms` : on ne peut pas faire
d'update vraiment incrémental (delete d'authorship → suppression de
sa contribution) parce qu'on ne sait pas quelles contributions
viennent de qui.

Schéma cible : `person_name_form_sources(name_form, person_id, source)`
en row-per-triple, drop des arrays. Permet update vraiment incrémental
(delete authorship → DELETE row(s) correspondante(s)) + traçabilité
complète.

Coût : migration SQL non-triviale + adaptation des consommateurs (il
y en a peu : matching cascade + queries admin). Bénéfice : suppression
de la phase de recalculation batch + traçabilité.
