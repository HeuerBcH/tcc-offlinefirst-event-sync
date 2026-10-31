"""Injeção de falha do cenário S9: descarte da resposta após o commit (plano, seção 5.6)."""
import random


class FaultInjector:
    def __init__(self, drop_response_rate=0.0, seed=0):
        self.drop_response_rate = drop_response_rate
        self._rng = random.Random(seed)

    def should_drop(self):
        # Sem sorteio quando a taxa é zero: a sequência do RNG só é consumida em S9.
        if self.drop_response_rate <= 0:
            return False
        return self._rng.random() < self.drop_response_rate
