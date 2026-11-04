from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

GLOBAL_KEY = "*"


class LoginThrottle:
    """Freine les échecs de connexion locale, par origine et globalement.

    En mémoire, pour un seul processus uvicorn : un redémarrage remet les
    compteurs à zéro, ce qui reste acceptable pour un frein (ce n'est pas un
    verrou de compte). Le seuil global couvre une attaque répartie sur plusieurs
    origines ; on ne bloque pas par nom d'utilisateur, ce qui permettrait à
    n'importe qui de fermer la porte à l'administrateur.
    """

    def __init__(
        self,
        *,
        max_per_origin: int = 5,
        max_global: int = 50,
        window_s: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = {GLOBAL_KEY: max_global}
        self._max_per_origin = max_per_origin
        self._window_s = window_s
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}

    def is_blocked(self, origin: str) -> bool:
        return any(len(self._recent(key)) >= self._limit(key) for key in (origin, GLOBAL_KEY))

    def record_failure(self, origin: str) -> None:
        now = self._clock()
        for key in (origin, GLOBAL_KEY):
            self._failures.setdefault(key, deque()).append(now)

    def _limit(self, key: str) -> int:
        return self._limits.get(key, self._max_per_origin)

    def _recent(self, key: str) -> deque[float]:
        window = self._failures.get(key)
        if window is None:
            return deque()
        horizon = self._clock() - self._window_s
        while window and window[0] <= horizon:
            window.popleft()
        return window
