# optimize_goal Contracts

`optimize_goal` now has two separate contracts:

1. `opt_settings.schema.json`
- Purpose: runtime optimization/simulation settings contract (the original `*_settings.json` format).
- Example: `5t_ota_settings.json`.

2. `design_specs.schema.json`
- Purpose: readable design-spec contract extracted from settings for downstream tools and human review.
- Example: `5t_ota_design_specs.example.json`.

## File Layout
- `opt_settings.schema.json`: schema for `*_settings.json`.
- `design_specs.schema.json`: schema for extracted `*_design_specs.json`.
- `../prompts/optimize_goal/specs_extractor.md`: extractor prompt template used by the tool.
- `extract_design_specs.py`: internal settings-to-specs extraction.
- `5t_ota_settings.json`: settings example.
- `5t_ota_design_specs.example.json`: extracted specs example.

## `opt_settings` vs `design_specs`

`opt_settings` keeps all optimizer/runtime knobs:
- `ocn_script`, `des_vars`, `responses`, `outputs`, `options`, `objective`, ...

`design_specs` keeps only spec-facing information:
- `schema_version`
- `topology`
- `objective`
- `design_variables[]`
- `performance_specs[]`

This split is intentional:
- simulator/optimizer reads `opt_settings`
- spec interpretation and cross-tool contracts read `design_specs`

## design_specs Mapping Rules

Source is one `*_settings.json` object.

1. Objective
- `objective.metric <- settings.objective.name`
- `objective.sense <- settings.objective.minormax` (`min|max`)

2. Design variables
- iterate `settings.des_vars` in key order
- each variable `[min, max]` or `[min, max, is_int]` maps to:
  - `name`
  - `min`
  - `max`
  - `is_integer` (boolean)

3. Performance specs
- iterate metrics by `settings.responses.assembler` order
- for each metric, read `settings.outputs[metric] = [threshold, method, weight, calc_expr]`
- mapping:
  - `method=min -> rule=">="`
  - `method=max -> rule="<="`
  - `method=target -> rule="target"`
- `index` equals position in `responses.assembler`
- `is_objective` is true only when metric equals `objective.metric`

## Internal extraction

The initialization and iterative-sizing pipelines automatically generate
`design_specs` from the selected case settings. This is an internal preprocessing
step and is not exposed as a user-facing CLI command.

## Validation Rules (Fail-fast)

Extractor validates:
- required fields exist: `des_vars`, `responses.assembler`, `outputs`, `objective`
- each response metric exists in `outputs`
- `objective.name` exists in `responses.assembler`
- `objective.minormax` is `min|max`
- output method is `min|max|target`

Invalid input raises a clear validation error.

## Prompt Source

The extractor loads and renders:
- `src/agentic_sizing/resources/prompts/specs/specs_extractor.md`

If the prompt file is missing or empty, extraction fails immediately.
