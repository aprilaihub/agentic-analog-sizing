"""Optional adapter for user-supplied Cadence projects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(slots=True)
class CadenceSimulationAdapter:
    settings_path: str | Path
    design_var_order: Sequence[str]
    perf_order: Sequence[str]

    def simulate(self, design_vars: dict[str, float]) -> dict[str, float]:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Install agentic-sizing[cadence] to use CadenceSimulationAdapter"
            ) from exc
        from .interfacing import assembler
        from .utils import parse_yaml

        settings = parse_yaml(str(Path(self.settings_path).expanduser().resolve()))
        values = np.asarray([[float(design_vars[name]) for name in self.design_var_order]])
        performance, _ = assembler(settings, values)
        row = performance[0] if getattr(performance, "ndim", 1) > 1 else performance
        return {name: float(row[index]) for index, name in enumerate(self.perf_order)}
