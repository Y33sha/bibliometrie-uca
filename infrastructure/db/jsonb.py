"""Le type JSONB du projet.

`Jsonb` écrit `None` en NULL SQL. Le type de SQLAlchemy, lui, le sérialise en JSON `null` : deux valeurs que Python relit toutes deux en `None`, mais que SQL distingue. Une colonne qui mélange les deux formes échappe aux contraintes et aux index qui raisonnent sur NULL — un unique `NULLS NOT DISTINCT` laisse passer le doublon, un index partiel `WHERE col IS NOT NULL` indexe des lignes vides, `col IS NULL` en manque une part.

Le type s'utilise partout où une valeur JSON s'écrit : en colonne de table et en paramètre lié.
"""

from sqlalchemy.dialects.postgresql import JSONB

Jsonb = JSONB(none_as_null=True)
