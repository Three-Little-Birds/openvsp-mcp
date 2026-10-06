# Contribution roadmap: constrained aircraft generation

## First contribution

The initial fork exposed three tools that required pre-existing models and raw
AngelScript. Inspection ran a script that rewrote its input, execution returned a
path under a deleted temporary directory, success depended on process exit codes,
and fresh installations could select an incompatible MCP SDK major version.

The current changes establish a deterministic conventional-aircraft builder,
explicit units and parameter conventions, saved-native-value checks, retained
artifacts, read-only inspection, atomic replacement after successful raw edits,
timeouts, SDK compatibility bounds, and tested MCP protocol exchanges.

The client LLM maps language into the aircraft specification and chooses permitted
design changes. The server sizes, builds, and measures each candidate. Constraint
success is based on measured native parameters and bounding boxes.

## Sizing and revision contribution

The analytical planner solves bounded conventional-wing sizing with explicit
fixed/adjustable dimensions and SI targets. It reports conflicts before native
execution, preserves fixed inputs, and returns a build request carrying exact
targets and adjustable bounds into native verification. Bounding extents remain
deferred until construction. Its deterministic selection policy preserves the
baseline span and chord sum when feasible; this is not aerodynamic optimization.

Typed revisions reconstruct managed snapshots into new run directories, inherit
constraints by default, verify model/specification hashes, and record lineage.
Failed-constraint parents can be repaired without overwriting the original model.
Complete artifact bundles can be relocated. Externally edited models must first
be rebuilt from the intended specification.

## Next stages

1. **Artifact retrieval and preview.** Add authenticated downloads or scoped MCP
   resources for run artifacts, plus native mesh and orthographic previews.
   Cloud clients cannot use a server's local path as a download URL.
2. **Richer geometry.** Support ordered wing sections, station-based fuselages,
   asymmetric/canard/twin-tail layouts, explicit NACA/camber and file airfoils.
   Preserve strict schemas and validate saved values for every added degree of freedom.
3. **Broader sizing.** Extend the analytical planner beyond one trapezoidal wing
   to section-based planforms, station-based fuselages, tail-volume targets, and
   explicitly budgeted optimization objectives. Preserve fixed variables and carry
   every goal into native verification. Broader sizing must match the geometry
   representation and measurement conventions.
4. **Geometry integrity.** Verify intersections, minimum clearance, component
   connectivity, and analysis mesh quality with native geometric operations.
   Cross-section dimensions and bounding boxes alone cannot establish these properties.
5. **Aerodynamic constraints.** Generate VSPAERO geometry and solver inputs from the
   same saved candidate, run analyses, and parse native results and convergence.
   Keep geometry construction, solver setup, aerodynamic modeling, and optimization
   in separate modules. Do not equate a geometric pass with static stability or trim.
6. **Cross-client evaluations.** Run the same aircraft prompts through Claude and
   ChatGPT. Score dimension error, hard-constraint satisfaction, tool errors,
   recovery, call count, and reproducibility. Save specifications, tool traces,
   native models, and reports for regression comparisons.
7. **Hosted operation.** Add authentication, filesystem scoping, per-user artifact
   access, job limits/cancellation, and controlled execution for remote users.
   Raw script execution is currently a trusted-local/expert capability.

## Acceptance examples for future agent evaluations

- Build the supplied 4 m-span example with a 1.94 m² wing and all four components.
- Express the same geometry in feet and obtain the same saved SI model dimensions.
- Request an incompatible 3.5 m maximum span with a fixed 4 m span; report the
  conflict rather than asserting success or quietly resizing the wing.
- Permit span/chord changes within explicit bounds and repair that failed
  candidate through a fresh typed revision, retaining the parent and native reports.
- Modify a managed source outside the builder and reject revision on hash mismatch.
- Ask for projected span with dihedral; distinguish it from developed span.
- Recover from a missing native binary with an actionable path/configuration error.
- Request an unsupported aircraft layout; state the limitation before claiming
  the conventional template satisfies it.
- Require stability or trim; explain that aerodynamic analysis is needed and do
  not substitute geometric checks.

## Validation boundaries

The current suite verifies native OpenVSP geometry and MCP protocol behavior.
It does not use either provider's model API, configure accounts, publish a server,
or validate aerodynamic/structural feasibility. The standalone VSPAero wrapper
requires preconfigured solver inputs; full analysis setup is a later contribution.
