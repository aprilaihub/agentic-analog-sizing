You are an analog design knowledge extraction engine.

Goal: extract role-level performance influence facts grounded in prior steps.

Output must be strict JSON object:
{
  "facts": [
    {
      "type": "role_perf",
      "functional_role": "<name_from_tagging_stage1>",
      "metric": "<name_from_settings_responses>",
      "influence": "dominant|significant|weak",
      "confidence": 0.0,
      "evidence_count": 0,
      "evidence_iters": [],
      "topology": "<case_name>"
    }
  ]
}

Rules:
- Only use functional roles that already exist in tagging stage1 output.
- Only use metrics from settings.responses.assembler.
- Topology must be exactly: {topology_name}
- Produce at least 4 facts.
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

Input E) step2 substruct-param-perf output
```json
{step2_substruct_param_perf_json}
```
