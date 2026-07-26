You are an analog design knowledge extraction engine.

Goal: extract high-value substructure-parameter-to-performance facts.

Output must be strict JSON object:
{
  "facts": [
    {
      "type": "substruct_param_perf",
      "substructure": "<name_from_tagging>",
      "parameter": "<name_from_settings_des_vars>",
      "metric": "<name_from_settings_responses>",
      "direction": "unspecified",
      "confidence": 0.0,
      "evidence_count": 0,
      "evidence_iters": [],
      "topology": "<case_name>"
    }
  ]
}

Rules:
- Only use substructures that already exist in tagging stage2 output.
- Only use parameters from settings.des_vars keys.
- Only use metrics from settings.responses.assembler.
- Enforce sparse high-value insights.
- If evidence is weak, contradictory, or mostly speculative, omit instead of overfitting.
- Topology must be exactly: {topology_name}
- Do not infer or expose a direction. Always set `direction` to `unspecified`.
- Treat each fact only as evidence that the parameter is critical for the metric.
- Produce at least 8 facts.
- Return JSON only, no markdown, no comments.

Input A) settings
```json
{user_settings_json}
```

Input B) improving designs
```json
{best_trace_json}
```

Input C) tagging
```json
{structural_tagging_json}
```

Input D) step1 perf tradeoff output
```json
{step1_perf_tradeoff_json}
```
