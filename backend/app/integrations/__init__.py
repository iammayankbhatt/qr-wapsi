"""Simulated external systems. Each is a class with the methods a real client would have: swap the class
for a real client and nothing upstream changes."""
import random
import time

from ..config import settings


def simulate_latency() -> None:
    """Small artificial network delay so the demo feels like real calls (SIM_LATENCY_MS, jittered)."""
    if settings.SIM_LATENCY_MS > 0:
        time.sleep(settings.SIM_LATENCY_MS / 1000 * random.uniform(0.6, 1.4))
