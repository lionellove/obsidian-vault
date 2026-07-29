---
name: solve-high-pressure-fluid-volume
description: Research and compute the volume of a known mass of a fluid at extreme pressure and temperature. Use for GAIA or other scientific QA tasks that combine geographic or environmental conditions with refrigerant or chemical property data, equations of state, compressed-liquid density, unit conversion, and strict answer formatting.
---

# Solve High-Pressure Fluid Volume

Use an evidence table with one row each for fluid identity, mass, absolute
pressure, temperature, property method, and requested output unit. Attach a
source or derivation to every row.

## Build one state point

1. Normalize the substance name to an unambiguous identifier such as a
   refrigerant number, formula, CAS number, or database key.
2. Translate environmental prose into numerical pressure and temperature.
   Distinguish ambient conditions from extrema caused by unrelated local
   phenomena.
3. Prefer measured pressure over a depth-only hydrostatic estimate. When
   deriving pressure, include atmospheric pressure if the property method
   expects absolute pressure and account for seawater density variation when
   the precision warrants it.
4. Keep uncertainty bounds until the final rounding step.

## Select a defensible property route

Use the strongest available route:

- Direct tabulated density or specific volume at the target state.
- A validated equation-of-state library whose fluid model and range are
  documented.
- A published equation of state or correlation implemented transparently.
- A bounded engineering estimate based on nearby data and compressibility,
  used only when the requested precision permits it.

Reject convenient but physically mismatched routes: ideal gas below the
critical temperature at extreme pressure, saturation data substituted for a
compressed-liquid state, a different refrigerant, gauge pressure treated as
absolute, or extrapolation beyond a correlation's validity range.

## Compute and verify

Compute either `V = m / rho` or `V = m * v_specific`. Make dimensions explicit
in code and retain extra precision. Verify:

- the phase and density magnitude are physically plausible;
- nearby pressure or temperature changes move density in a plausible direction;
- an independent method or source agrees closely enough that the requested
  rounding is stable;
- the reported precision does not exceed source or state-condition precision.

## React when a property package is unavailable

Treat import failure as a local execution event, not evidence that the property
cannot be computed.

- First inspect the exact error and available packages.
- If installing dependencies is disallowed or unnecessary, pivot to a primary
  table, documented web calculator, or implementable published correlation.
- Never fabricate a library result and never present an unevaluated code block
  as the final answer.
- Recompute the state independently after switching methods.

Honor the question's output contract only after the evidence and dimensional
checks pass.
