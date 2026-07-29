---
name: solve-gaia-r12-trench-volume
description: Solve GAIA validation task 72c06643-a2fa-4186-aa5c-9ec33ae9b445 about the volume of a fixed mass of R-12 at Mariana Trench conditions. Use only for this task ID or an exact restatement of that question. Guides source selection, state-point construction, high-pressure property evaluation, unit conversion, verification, and integer-only output without embedding the reference answer.
---

# Solve the R-12 Trench Volume Task

Treat the task as a high-pressure thermodynamic state calculation, not as a
generic density lookup.

1. Parse the requested state and output contract before searching: mass, fluid
   identity, trench location, "peak temperature," pressure, requested volume
   unit, and rounding rule.
2. Resolve the location language. Establish whether "bottom of the Marianas
   Trench" means Challenger Deep and whether "peak temperature" means the
   maximum measured ambient bottom-water temperature rather than a
   hydrothermal-vent temperature. Prefer expedition or oceanographic sources.
3. Obtain pressure and temperature as separate cited facts. Prefer a directly
   reported in-situ pressure. If only depth is available, calculate pressure
   with a seawater-aware method and state the approximation.
4. Treat Freon-12 as refrigerant R-12 / dichlorodifluoromethane and confirm the
   identifier before using any property source.
5. Evaluate density or specific volume at the same pressure-temperature point.
   Prefer, in order:
   - a documented equation-of-state implementation or primary property table;
   - a trusted property database covering compressed liquid;
   - a reproducible equation of state with cited coefficients and validity
     range.
6. Do not use an ideal-gas law or saturated-liquid table at approximately one
   atmosphere for this deep-ocean state. Do not silently extrapolate outside a
   model's pressure range.
7. Record every conversion in code, including absolute versus gauge pressure,
   Celsius to kelvin, kilograms to the property's mass unit, cubic metres to
   millilitres, and density versus specific volume.
8. Compute volume from one internally consistent state point. Then perform an
   independent plausibility check using a second source, nearby state points,
   or a bounded compressed-liquid density estimate.
9. If a desired property package is unavailable in the code sandbox, do not
   end with installation attempts or return code as the answer. Switch to a
   web-accessible table, published correlation, or manual equation-of-state
   calculation.
10. Round only the final millilitre value and return exactly one base-10
    integer with no unit or explanation.

Do not read any prior output file containing the reference answer. Evidence
must come from the question, public sources, and independently reproduced
calculations.
