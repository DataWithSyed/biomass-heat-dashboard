"""Interactive screening dashboard for biomass gasification process-heat chains (logic layer)."""
from .core import (Requirement, PRESETS, CHAIN_LABELS, load_matrix, precomputed_view,
                   cost_inputs_for, live_view, best_feasible, co2_curve, default_sizing,
                   load_prices)

__version__ = "0.1.0"
