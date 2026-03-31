from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


COMPONENT_MOLECULAR_WEIGHTS = {
    'N2': 28.0134,
    'CO2': 44.0095,
    'C1': 16.043,
    'C2': 30.07,
    'C3': 44.097,
    'I-C4': 58.124,
    'N-C4': 58.124,
    'I-C5': 72.151,
    'N-C5': 72.151,
    'C6': 86.178,
    'C7': 100.205,
    'C8': 114.232,
    'C9': 128.259,
}

HEAVY_COMPONENTS = {'C6', 'C7', 'C8', 'C9', 'C10+'}


@dataclass(slots=True)
class CompositionScenario:
    key: str
    label: str
    source: str
    estimated_gor_sm3_sm3: float | None
    components_mol_pct: dict[str, float]
    plus_mw_g_mol: float | None = None
    plus_density_g_cc: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_components(self) -> dict[str, float]:
        total = sum(self.components_mol_pct.values())
        if total <= 0:
            return dict(self.components_mol_pct)
        return {name: value / total for name, value in self.components_mol_pct.items()}

    @property
    def mixture_mw_g_mol(self) -> float:
        normalized = self.normalized_components
        plus_mw = self.plus_mw_g_mol or 250.0
        mw = 0.0
        for name, fraction in normalized.items():
            if name == 'C10+':
                mw += fraction * plus_mw
            else:
                mw += fraction * COMPONENT_MOLECULAR_WEIGHTS.get(name, plus_mw)
        return mw

    @property
    def heavy_fraction(self) -> float:
        normalized = self.normalized_components
        return sum(normalized.get(name, 0.0) for name in HEAVY_COMPONENTS)


@dataclass(slots=True)
class BackendStatus:
    available: bool
    mode: str
    detail: str
