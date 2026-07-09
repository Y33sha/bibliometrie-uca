"""Port : ouvreur de transaction pour les orchestrateurs de phase.

Un orchestrateur de phase (`application/pipeline/<phase>/`) ne connaît ni l'engine ni
`infrastructure/`. Pour ouvrir ses transactions, il reçoit un `OpenTransaction` : un
appelable qui rend une transaction gérée en context-manager — commit en sortie de bloc si
succès, rollback sur exception, close. Le composition-root (`run_pipeline`) le fournit ;
`Engine.begin` le satisfait tel quel.

Unit of work en forme fonction : une phase enchaîne autant de transactions indépendantes
qu'elle a de sous-étapes, chacune dans son propre `with open_tx() as conn`. Pas d'objet
`UnitOfWork` ni de registry de repositories — les adapters d'une phase sont injectés à côté.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy import Connection

OpenTransaction = Callable[[], AbstractContextManager[Connection]]
