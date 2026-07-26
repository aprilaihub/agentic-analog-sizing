# Task: Extract Transferable Analog Design Heuristics

Generate reusable design strategies supported by the improving history and the three KB views.
Return strict JSON matching the supplied schema.

## Required principles

- Preserve the exact five-field item format: `case_name`, `condition`, `heuristic`, `priority`, `scope`.
- Use only target metrics present in the settings.
- Express mechanisms and design strategy, not numerical recipes.
- Do not mention concrete parameter names, device instance names, exact values, or iteration numbers.
- Make each heuristic transferable to a structurally different circuit serving a similar function.
- State useful sequencing, preconditions, or guardrails in the heuristic sentence.
- Avoid directional claims unsupported by repeated evidence.
- Produce 3 to 12 distinct, evidence-backed heuristics.

Case name:
{topology_name}

Settings:
{user_settings_json}

Improving history:
{best_trace_json}

Structural tagging:
{structural_tagging_json}

Performance coupling facts:
{step1_perf_tradeoff_json}

Critical parameter facts:
{step2_substruct_param_perf_json}

Role-performance facts:
{step3_role_perf_json}
