"""Original dimensional accounting for explicit operational-energy scenarios.

No provider model catalog, estimated parameter counts, or third-party regression
coefficients are used. There is no built-in calibrated Gemini energy estimate.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from carbontrace.domain import ImpactResult, Interval


def estimate_operational_impact(
    allocated_power_w: Interval, seconds: float, pue: float, grid_g_per_kwh: float
) -> ImpactResult:
    """Apply E(Wh)=allocated W × seconds/3600 × PUE; GWP(g)=E/1000 × g/kWh.

    Allocated power must already account for sharing between concurrent requests.
    This method excludes training, hardware manufacture, network, and user devices.
    Its caller must label whether each input is measured or merely assumed.
    """
    import math

    if not all(math.isfinite(value) for value in (seconds, pue, grid_g_per_kwh)):
        raise ValueError("Inputs must be finite")
    if seconds < 0 or pue < 1 or grid_g_per_kwh < 0:
        raise ValueError("Invalid time, PUE, or electricity factor")
    factor = seconds / 3600 * pue
    energy = Interval(
        low=allocated_power_w.low * factor, high=allocated_power_w.high * factor
    )
    return ImpactResult(
        energy_wh=energy,
        carbon_g=Interval(
            low=energy.low / 1000 * grid_g_per_kwh,
            high=energy.high / 1000 * grid_g_per_kwh,
        ),
    )


def sum_impacts(impacts: Sequence[ImpactResult]) -> ImpactResult | None:
    """Aggregate all attempted generations, including failed quality gates."""
    if not impacts:
        return None
    return ImpactResult(
        energy_wh=Interval(
            low=sum(item.energy_wh.low for item in impacts),
            high=sum(item.energy_wh.high for item in impacts),
        ),
        carbon_g=Interval(
            low=sum(item.carbon_g.low for item in impacts),
            high=sum(item.carbon_g.high for item in impacts),
        ),
    )


def compare_intervals(
    baseline: ImpactResult | None, selected: ImpactResult | None
) -> Literal["unavailable", "lower", "higher", "overlap"]:
    """Declare a direction only when the operational GWP bounds do not overlap."""
    if baseline is None or selected is None:
        return "unavailable"
    if selected.carbon_g.high < baseline.carbon_g.low:
        return "lower"
    if selected.carbon_g.low > baseline.carbon_g.high:
        return "higher"
    return "overlap"
