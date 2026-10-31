"""Gerador determinístico de operações (plano, seção 4.4).

A sequência completa é pré-computada a partir da semente, antes de t0, simulando o estado
das entidades. Mesma semente e mesmos parâmetros produzem a mesma sequência.
"""
import string
import time
import uuid
from dataclasses import dataclass
from random import Random

CREATE, UPDATE, DELETE = "CREATE", "UPDATE", "DELETE"
FIELDS = ("title", "description", "value")
ALPHABET = string.ascii_letters + string.digits
VALUE_MIN, VALUE_MAX = 100000, 999999  # inteiro sempre com 6 dígitos


@dataclass(frozen=True)
class Operation:
    index: int
    event_id: str
    operation: str
    entity_id: str
    payload: dict
    requested: str  # tipo sorteado antes da regra "sem entidade viva vira CREATE"


def _uuid4(rng):
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _text(rng, length):
    return "".join(rng.choices(ALPHABET, k=length))


def _field_value(rng, field, text_len):
    if field == "value":
        return rng.randint(VALUE_MIN, VALUE_MAX)
    return _text(rng, text_len)


def generate_operations(n, seed, mix=(0.30, 0.60, 0.10), text_len=64):
    if abs(sum(mix) - 1.0) > 1e-9:
        raise ValueError(f"a mistura de operações deve somar 1: {mix}")
    rng = Random(seed)
    p_create, p_update, _ = mix
    alive = []  # entidades existentes e não excluídas, em ordem determinística
    ops = []
    for i in range(n):
        r = rng.random()
        requested = CREATE if r < p_create else UPDATE if r < p_create + p_update else DELETE
        kind = requested if (requested == CREATE or alive) else CREATE
        event_id = _uuid4(rng)
        if kind == CREATE:
            entity_id = _uuid4(rng)
            payload = {f: _field_value(rng, f, text_len) for f in FIELDS}
            alive.append(entity_id)
        elif kind == UPDATE:
            entity_id = alive[rng.randrange(len(alive))]
            field = rng.choice(FIELDS)
            payload = {field: _field_value(rng, field, text_len)}
        else:
            entity_id = alive.pop(rng.randrange(len(alive)))
            payload = {}
        ops.append(Operation(i, event_id, kind, entity_id, payload, requested))
    return ops


def operation_counts(ops):
    """Contagem real por tipo e quantas operações sorteadas como UPDATE/DELETE viraram CREATE."""
    counts = {CREATE: 0, UPDATE: 0, DELETE: 0}
    requested = {CREATE: 0, UPDATE: 0, DELETE: 0}
    for op in ops:
        counts[op.operation] += 1
        requested[op.requested] += 1
    converted = sum(1 for op in ops if op.operation != op.requested)
    return {"actual": counts, "requested": requested, "converted_to_create": converted}


def run_generation(ops, store, interval_s, start_monotonic, on_recorded, on_queue_full, stop_event):
    """Aplica a operação i no instante start + i × intervalo, sem acumular atraso.

    Devolve quantas operações foram processadas (gravadas ou recusadas por QUEUE_FULL).
    """
    done = 0
    for op in ops:
        delay = start_monotonic + op.index * interval_s - time.monotonic()
        if delay > 0 and stop_event.wait(delay):
            break
        if stop_event.is_set():
            break
        if store.record(op) is None:
            on_queue_full(op)
        else:
            on_recorded(op)
        done += 1
    return done
