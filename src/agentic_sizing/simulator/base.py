from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Protocol


class SimulationAdapter(Protocol):
    def simulate(self, design_vars: Dict[str, float]) -> Dict[str, float]:
        """Run simulation and return performance dictionary."""


@dataclass
class MockSimulationAdapter:
    """Deterministic mock simulator used for state-machine demos."""

    seed: int = 2026

    def simulate(self, design_vars: Dict[str, float]) -> Dict[str, float]:
        gm1 = float(design_vars.get("gm1", 1.0))
        gm2 = float(design_vars.get("gm2", 1.0))
        rout = float(design_vars.get("rout", 8.0))
        cc = float(design_vars.get("cc", 1.0))
        ibias = float(design_vars.get("ibias", 1.0))

        gain = 30.0 + 8.0 * gm1 + 1.5 * rout
        ugb = 5.0e6 + 2.2e6 * gm2 + 6.0e5 * cc
        pm = 48.0 + 3.0 * cc - 0.4 * gm2
        power = 0.7 + 0.18 * gm1 + 0.23 * gm2 + 0.15 * ibias

        return {
            "gain": gain,
            "ugb": ugb,
            "pm": pm,
            "power": power,
        }
