"""Ports du domaine — interfaces abstraites que les adapters
(infrastructure) doivent implémenter.

En architecture hexagonale, les ports vivent dans le domaine et
décrivent les capacités dont la couche métier a besoin. Les adapters
concrets (PostgreSQL, HTTP, fichiers) vivent dans infrastructure/ et
implémentent ces ports.

L'intérêt :
- Le domaine et l'application ne dépendent jamais de l'infrastructure,
  ils ne voient que des Protocols abstraits.
- Les tests peuvent fournir des implémentations fictives (fakes) qui
  respectent le Protocol sans avoir besoin d'une base de données.
- Changer d'impl (ex. PostgreSQL → autre) ne touche ni le domaine ni
  l'application, seulement les adapters dans infrastructure/.

Les Protocols Python utilisent le duck typing structurel : une classe
qui a les bonnes méthodes satisfait le Protocol sans héritage explicite.
"""
