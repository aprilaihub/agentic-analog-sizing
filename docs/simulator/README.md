# Simulator Improving-Designs Contract

## Purpose
This document defines the JSON data contract for simulator improving-designs trace files.

Contract files:
- Schema: `src/agentic_sizing/simulator/improving_designs.schema.json`
- Example: `examples/data/5t_ota_improving_designs.json`

## Scope
- This contract is for improving best-trace history only.
- It is used as structured input to KB extraction.
- It does not define raw simulator CSV format.

## Top-Level Structure
- Type: JSON array
- Each item is one improving design point.

Required fields per item:
- `iter`
- `parameters`
- `performance`
- `validation`
- `objective`
- `violations`

## Field Definitions
- `iter`:
  - Type: integer (>= 0)
  - Meaning: optimization iteration index
- `parameters`:
  - Type: number array
  - Meaning: design variables in `settings.des_vars` order
- `performance`:
  - Type: number array
  - Meaning: performance metrics in `settings.responses.assembler` order
- `validation`:
  - Type: number
  - Meaning: composite score used to rank best candidate
- `objective`:
  - Type: number
  - Meaning: objective scalar (current ESSAB convention maps to `performance[0]`)
- `violations`:
  - Type: number (>= 0)
  - Meaning: aggregated constraint violation score

## Ordering Rules
- Parameter ordering is determined by `settings.des_vars` key order.
- Performance ordering is determined by `settings.responses.assembler`.
- In current 5t_ota settings, `settings.responses.assembler` and `settings.outputs` orders are aligned.

## 5t_ota Instance Notes
Based on:
- `src/agentic_sizing/specs/5t_ota_settings.json`
- `examples/data/5t_ota_improving_designs.json`

Observed dimensions:
- `parameters` length = 7
- `performance` length = 10
- trace item count = 17
- `iter` range = 0 -> 445

## Semantic Consistency Rules (non-schema)
Recommended checks for tooling:
- `iter` should be strictly increasing and unique.
- `objective` should equal `performance[0]` under current ESSAB convention.
- `validation` should satisfy `validation ~= objective + violations` (floating-point tolerance allowed).

## Relation to KB Extraction
KB tool input `--improving-designs` expects this structure:
- `agentic_sizing/kb/__main__.py`
- `agentic_sizing/kb/pipeline.py`

The trace is consumed as history evidence for:
- perf-perf tradeoff facts
- substructure-parameter-performance facts
- role-performance facts
