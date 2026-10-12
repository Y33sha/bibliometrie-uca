"""Chaîne des exceptions d'un échec de phase.

Une exception levée pendant le nettoyage d'une autre la masque : l'annulation d'une transaction sur une connexion perdue lève `PendingRollbackError`, et l'erreur d'origine reste dans `__cause__` ou `__context__`.
"""


def exception_chain(exc: BaseException) -> list[BaseException]:
    """L'exception, puis celles qu'elle masque, de la plus récente à celle d'origine."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def is_user_interruption(exc: BaseException) -> bool:
    """Vrai si l'échec part d'une interruption clavier."""
    return any(isinstance(e, KeyboardInterrupt) for e in exception_chain(exc))


def failure_message(exc: BaseException) -> str:
    """Message d'un échec : l'erreur d'origine d'abord, puis celle qui la masque."""
    origin = exception_chain(exc)[-1]
    if origin is exc or str(origin) in str(exc):
        return str(exc)
    return f"{type(origin).__name__} : {origin} — puis {type(exc).__name__} : {exc}"
