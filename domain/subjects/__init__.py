"""Concept métier Sujet : libellés agrégés depuis les ontologies sources.

Un sujet est un libellé observé sur des publications, dédupliqué sur
`lower(label)`, annoté par les ontologies sources qui l'ont produit
(HAL CCSD, OpenAlex topics/keywords, WoS subjects, RAMEAU, theses
discipline, ScanR domain).

Sous-modules :
- ``subject`` : constantes d'ontologies + helpers de normalisation
  des libellés.
"""
