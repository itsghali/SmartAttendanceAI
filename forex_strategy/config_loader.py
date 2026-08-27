"""Central configuration loader.

Loads config.yaml into a plain dict and provides a small helper to apply
overrides (used by sensitivity analysis / walk-forward testing, which must
run many backtests with different parameter combinations without ever
mutating the on-disk baseline config).
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict

import yaml

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    return cfg


def with_overrides(base_config: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep copy of base_config with top-level keys overridden.

    Nested dicts (e.g. transaction_costs) are replaced wholesale if present
    in overrides; scalar keys are simply set.
    """
    cfg = copy.deepcopy(base_config)
    for key, value in overrides.items():
        cfg[key] = value
    return cfg
