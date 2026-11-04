# Plan de rattachement des revues

## Contexte

Le rattachement des enregistrements sources aux revues (`pipeline/transformation/publishing/serials/attach_serials.py`) écrit en base pendant son calcul :

- `_issn_serials` crée la revue d'un ISSN-L en cours de calcul ;
- `_attach` crée la revue sans ISSN d'un titre en cours de calcul, et cherche en base la revue sans ISSN existante de ce titre.

Les règles élémentaires sont dans `domain.serials.attachment`. Leur enchaînement reste dans le pipeline : environ 250 lignes, testées seulement contre une base.

Les éditeurs et les monographies suivent un autre modèle. Le domaine calcule un plan complet, avec des références aux entités à créer : `PublisherAttachment` et `NewPublisher` (`domain.publishers.attachment`), `group_volumes` (`domain.monographs.attachment`). Le pipeline crée ces entités, puis écrit les liens.

## Décisions

- **Le domaine calcule le plan des revues** : revue de chaque ISSN-L, revue de chaque enregistrement source, compte des rattachements par voie. Une revue à créer y figure comme référence, sur le modèle de `NewPublisher`.
- **Le domaine reçoit les revues sans ISSN**, et retrouve celle d'un titre sans requête.
- **Le pipeline lit les faits, crée les revues du plan, puis écrit les liens.** L'absorption des revues vidées et l'écriture du titre et du modèle OA des revues suivent.
- **Les rattachements restent identiques**, vérifiés par une comparaison avant et après sur la base locale, en transaction annulée.

## Phasage

### Phase 1 — Plan des ISSN-L

- [ ] Revue de chaque ISSN-L calculée par le domaine, revues à créer en références.
- [ ] Tests unitaires du plan des ISSN-L.

### Phase 2 — Plan des enregistrements sources

- [ ] Revue de chaque enregistrement source calculée par le domaine, revues sans ISSN à créer en références.
- [ ] Tests unitaires du plan des enregistrements sources.

### Phase 3 — Écriture

- [ ] Le pipeline crée les revues du plan et écrit les liens.
- [ ] Comparaison des rattachements avant et après sur la base locale : zéro différence.

## Questions ouvertes

- Le titre et le modèle OA des revues (`_refresh_attributes`) entrent-ils aussi dans le plan ?
