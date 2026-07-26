You are given:
- A transistor-level netlist
- A JSON functional partition of the circuit

Using the functional partition as context, identify circuit substructures inside each functional role.

Use this canonical ontology.

Allowed `base_type` values:
- `differential_pair`
- `current_source`
- `current_mirror`
- `gain_stage`
- `source_follower`
- `resistor_divider`
- `miller_compensation`
- `capacitive_feedback_network`
- `cross_coupled_pair`
- `diode_connected_device`

Allowed `modifiers` values:
- `active_load`
- `bias`
- `cascode`
- `common_gate`
- `common_source`
- `folded`
- `output`
- `reference`
- `tail`
- `testbench`

Allowed canonical `type` labels:
- `Differential pair`
- `Current source`
- `Tail current source`
- `Reference current source`
- `Bias current source`
- `Cascode current source`
- `Current mirror`
- `Cascode current mirror`
- `Gain stage`
- `Cascode`
- `Folded cascode`
- `Common-source stage`
- `Common-gate stage`
- `Source follower`
- `Resistor divider`
- `Miller compensation`
- `Capacitive feedback network`
- `Cross-coupled pair`
- `Diode-connected device`

Return valid JSON only in this format:
{
  "roles": [
    {
      "name": "Main signal path",
      "substructures": [
        {
          "type": "Differential pair",
          "base_type": "differential_pair",
          "modifiers": [],
          "devices": [],
          "evidence": " ",
          "confidence": 0.0,
          "variables": [
            {
              "device": "M1",
              "design_variables": ["l2", "w2"]
            }
          ]
        }
      ]
    }
  ]
}

Decision rules:
- `type` must exactly match the canonical label implied by `base_type` and `modifiers`.
- Prefer function-first labeling. If a branch primarily biases or supplies current, use `current_source` or `current_mirror`, not `gain_stage`.
- Use `gain_stage` only for signal-path amplification structures.
- Use modifier `cascode` when cascoding is present, but keep the primary function in `base_type`.
- Do not label the same structure as both `common_source` and `current_source`.
- `common_source`, `common_gate`, and `folded` modifiers are only for `gain_stage`.
- `tail`, `reference`, and `bias` modifiers are only for `current_source`.
- Use the most specific valid canonical label.
- Devices must belong to the functional role assigned in Step 1.
- Do not invent new devices.
- Substructures must be supported by connectivity evidence.
- In `variables[].design_variables`, include symbolic design variables only (for example `l2`, `w2`, `Idc`, `N1`), not parameter names.

Netlist:
```spice
{netlist}
```

Functional partition from Step 1:
```json
{functional_partition_json}
```
