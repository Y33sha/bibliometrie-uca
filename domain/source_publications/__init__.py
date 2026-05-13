"""Concept métier ``SourcePublication`` — vue d'un document depuis une
source externe (HAL, OpenAlex, WoS, theses.fr, ScanR, …).

Aggregate séparé de ``Publication`` : lifecycle autonome. Une
`SourcePublication` naît à l'extraction, peut vivre non-attachée
pendant la dédup, puis s'attache (ou se réattache) à une `Publication`
canonique.

Sous-modules :
- ``source_publication`` : aggregate root ``SourcePublication``
- ``source_authorship`` : entité fille ``SourceAuthorship``
"""
