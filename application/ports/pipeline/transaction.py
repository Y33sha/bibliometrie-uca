"""Port : ouvreur de transaction pour les orchestrateurs de phase.

Un orchestrateur de phase (`application/pipeline/<phase>/`) ne connaît ni l'engine ni `infrastructure/`. Pour ouvrir ses transactions, il reçoit un `OpenTransaction` : un appelable qui rend une transaction gérée en context-manager — commit en sortie de bloc si succès, rollback sur exception, close. Le composition-root (`run_pipeline`) le fournit ; `infrastructure.db.transaction.managed_transaction` le satisfait — il tolère les commits par lots émis dans le bloc (phases à progression durable), là où `Engine.begin` lèverait en sortie.

Unit of work en forme fonction : une phase enchaîne autant de transactions indépendantes qu'elle a de sous-étapes, chacune dans son propre `with open_tx() as conn`. Réifier un objet `UnitOfWork` (transaction + registry de repositories) collerait mal à cette séquence de transactions hétérogènes, et les gateways de requêtes (`Pg*Queries`, sans état, prenant `conn` par appel) n'y auraient pas leur place : les adapters d'une phase sont injectés à côté.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import Connection

OpenTransaction = Callable[[], AbstractContextManager[Connection]]
