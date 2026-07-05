# Chantier — Cascade personnes : ordre-indépendance et consensus d'attribution

Commencé le 2026-07-04

Rendre le résultat de la phase personnes indépendant de l'ordre d'ingestion, sans changer la nature de la cascade ni son lookup en égalité de chaîne. Deux corrections ciblées : une fusion rétroactive qui rattrape les doublons qu'un ordre défavorable a créés, et un départage par consensus de l'attribution des identifiants, révisable quand une majorité postérieure contredit une attribution initiale.

## Contexte

### Problème 1 — dépendance à l'ordre d'ingestion

La cascade rattache ou crée, sans jamais reconsidérer une entité existante. Le résultat dépend donc de l'ordre d'arrivée des signatures. Le cas résiduel tient à l'asymétrie du matching par forme de nom : une personne créée à partir d'une forme initiale (« J Martin ») ne peut pas engendrer la forme pleine (« Jean Martin »), alors qu'une personne créée en forme pleine engendre l'initiale. Selon l'ordre, deux signatures d'une même personne aboutissent donc à une ou deux fiches.

### Problème 2 — attribution d'identifiant au premier arrivé

Une valeur d'identifiant est captée par la première signature qui la porte : la personne alors créée en devient le détenteur, figé par la contrainte `UNIQUE (id_type, id_value)`. Si cette première signature est erronée (identifiant recopié sur le mauvais co-auteur par une source), les signatures correctes ultérieures voient leur match refusé par corroboration de nom et retombent en création — l'identifiant reste collé à la mauvaise personne, les bonnes signatures s'éparpillent en doublons. Aucune majorité postérieure ne peut contester l'attribution initiale.

## Décisions

- **Ordre-indépendance par fusion rétroactive**. Quand une évidence postérieure montre que deux fiches n'en sont qu'une (une forme plus complète relie l'initiale et le plein), on fusionne après coup. La correction se fait hors du chemin chaud.
- **Attribution d'identifiant par consensus**, recalculable : le détenteur d'une valeur est celui que soutient la majorité des signatures qui la portent, pas le premier arrivé. Une majorité postérieure peut contester une attribution initiale devenue minoritaire.
- **Le noyau humain reste intangible** : identifiant `confirmed`, forme de nom `confirmed`/`rejected`, `distinct_persons`, paires `(publication, personne)` rejetées. Ni la fusion rétroactive ni le consensus ne passent outre.

## Phasage

### Phase 1 — Cascade ordre-indépendante

- [x] Générateur de formes unifié à la création + ordre de traitement déterministe (`fetch_unlinked_authorships`).
- [ ] Fusion rétroactive du cas « initiale puis pleine » : détecter deux fiches reliées par une forme plus complète et les fusionner, sous respect du noyau.

### Phase 2 — Consensus d'attribution d'identifiant

- [ ] Recalcul du détenteur d'une valeur d'identifiant à la majorité des signatures qui la portent.
- [ ] Contestation d'une attribution minoritaire par une majorité postérieure, sans jamais déloger une attribution `confirmed`.
- [ ] Repérage des attributions renversées pour contrôle admin.

## Questions ouvertes

- **Rôle de `author_identifying_keys` dans la cascade, et colonne `person_id` éventuelle.** Rendre la résolution identité → personne explicite et recalculable sur cette table, plutôt qu'implicite dans la première fiche créée, pourrait porter le consensus. À étudier : est-ce nécessaire, ou le support signature (`source_authorships.person_id`) suffit-il ?
- **Déclenchement et garde-fous de la fusion rétroactive.** Quelle évidence autorise une fusion (forme plus complète, mais laquelle exactement), à quel moment du pipeline elle passe, comment rester conservateur (ne fusionner que le franc, laisser le douteux séparé).
- **Mécanique du consensus.** Majorité de quoi (signatures brutes, pondérées par source ?), départage des égalités, articulation avec la corroboration de nom existante.
