"""Implicit online recalibrator (updates spatial bias offset from clicks and Semantic Lens choices)."""

from __future__ import annotations

import math
from typing import Tuple


class OnlineRecalibrator:
    """Maintains an exponentially-weighted moving bias offset (dx, dy) from user confirmations."""

    def __init__(self, outlier_sigma_mult: float = 3.5) -> None:
        self.bias_x: float = 0.0
        self.bias_y: float = 0.0
        self.updates_count: int = 0
        self.outlier_sigma_mult = outlier_sigma_mult

    @property
    def offset(self) -> Tuple[float, float]:
        return (self.bias_x, self.bias_y)

    def update(
        self,
        est_x: float,
        est_y: float,
        true_x: float,
        true_y: float,
        sigma: float = 120.0,
        weight: float = 0.20,
    ) -> bool:
        """Update bias offset if error is within 3.5 * sigma outlier guard."""
        err_x = est_x - true_x
        err_y = est_y - true_y
        dist = math.hypot(err_x, err_y)
        if dist > self.outlier_sigma_mult * max(sigma, 40.0):
            return False
        w = max(0.01, min(weight, 0.5))
        self.bias_x = (1.0 - w) * self.bias_x + w * err_x
        self.bias_y = (1.0 - w) * self.bias_y + w * err_y
        self.updates_count += 1
        return True

    def reset(self) -> None:
        self.bias_x = 0.0
        self.bias_y = 0.0
        self.updates_count = 0
