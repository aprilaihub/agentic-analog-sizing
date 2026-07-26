from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

CANONICAL_BASE_TYPES: List[str] = [
    "differential_pair",
    "current_source",
    "current_mirror",
    "gain_stage",
    "source_follower",
    "resistor_divider",
    "miller_compensation",
    "capacitive_feedback_network",
    "cross_coupled_pair",
    "diode_connected_device",
]

CANONICAL_MODIFIERS: List[str] = [
    "active_load",
    "bias",
    "cascode",
    "common_gate",
    "common_source",
    "folded",
    "output",
    "reference",
    "tail",
    "testbench",
]

CANONICAL_SUBSTRUCTURE_TYPES: List[str] = [
    "Differential pair",
    "Current source",
    "Tail current source",
    "Reference current source",
    "Bias current source",
    "Cascode current source",
    "Current mirror",
    "Cascode current mirror",
    "Gain stage",
    "Cascode",
    "Folded cascode",
    "Common-source stage",
    "Common-gate stage",
    "Source follower",
    "Resistor divider",
    "Miller compensation",
    "Capacitive feedback network",
    "Cross-coupled pair",
    "Diode-connected device",
]

LEGACY_TYPE_ALIASES: Dict[str, Tuple[str, List[str]]] = {
    "differential pair": ("differential_pair", []),
    "differential_pair": ("differential_pair", []),
    "current source": ("current_source", []),
    "tail current source": ("current_source", ["tail"]),
    "reference current source": ("current_source", ["reference"]),
    "bias current source": ("current_source", ["bias"]),
    "cascode current source": ("current_source", ["cascode"]),
    "cascode current sink": ("current_source", ["cascode"]),
    "current mirror": ("current_mirror", []),
    "cascode current mirror": ("current_mirror", ["cascode"]),
    "cascode mirror": ("current_mirror", ["cascode"]),
    "gain stage": ("gain_stage", []),
    "cascode": ("gain_stage", ["cascode"]),
    "cascode stage": ("gain_stage", ["cascode"]),
    "folded cascode": ("gain_stage", ["folded", "cascode"]),
    "common-source stage": ("gain_stage", ["common_source"]),
    "common source stage": ("gain_stage", ["common_source"]),
    "common-source": ("gain_stage", ["common_source"]),
    "common source": ("gain_stage", ["common_source"]),
    "common-gate stage": ("gain_stage", ["common_gate"]),
    "common gate stage": ("gain_stage", ["common_gate"]),
    "common-gate": ("gain_stage", ["common_gate"]),
    "common gate": ("gain_stage", ["common_gate"]),
    "source follower": ("source_follower", []),
    "resistor divider": ("resistor_divider", []),
    "miller compensation": ("miller_compensation", []),
    "capacitive feedback network": ("capacitive_feedback_network", ["testbench"]),
    "capacitive_feedback_network": ("capacitive_feedback_network", ["testbench"]),
    "cross-coupled pair": ("cross_coupled_pair", []),
    "cross coupled pair": ("cross_coupled_pair", []),
    "diode-connected device": ("diode_connected_device", []),
    "diode connected device": ("diode_connected_device", []),
}


STEP1_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["functional_roles"],
    "properties": {
        "functional_roles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "devices", "description"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "devices": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "description": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}

STEP2_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["roles"],
    "properties": {
        "roles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "substructures"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "substructures": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "type",
                                "base_type",
                                "modifiers",
                                "devices",
                                "evidence",
                                "confidence",
                                "variables",
                            ],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": CANONICAL_SUBSTRUCTURE_TYPES,
                                },
                                "base_type": {
                                    "type": "string",
                                    "enum": CANONICAL_BASE_TYPES,
                                },
                                "modifiers": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": CANONICAL_MODIFIERS,
                                    },
                                },
                                "devices": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                },
                                "evidence": {"type": "string", "minLength": 1},
                                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                "variables": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["device", "design_variables"],
                                        "properties": {
                                            "device": {"type": "string", "minLength": 1},
                                            "design_variables": {
                                                "type": "array",
                                                "items": {
                                                    "type": "string",
                                                    "minLength": 1,
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}

FINAL_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "tool", "input", "stage1", "stage2", "validation"],
    "properties": {
        "schema_version": {"type": "string", "minLength": 1},
        "tool": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "provider", "model", "generated_at_utc"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "provider": {"type": "string", "minLength": 1},
                "model": {"type": "string", "minLength": 1},
                "generated_at_utc": {"type": "string", "minLength": 1},
            },
        },
        "input": {
            "type": "object",
            "additionalProperties": False,
            "required": ["netlist_path", "subckt_name", "device_count"],
            "properties": {
                "netlist_path": {"type": "string", "minLength": 1},
                "subckt_name": {"type": "string"},
                "device_count": {"type": "integer", "minimum": 0},
            },
        },
        "stage1": STEP1_SCHEMA,
        "stage2": STEP2_SCHEMA,
        "validation": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "stage1_unique_assignment_ok",
                "stage2_role_membership_ok",
                "all_devices_known",
                "duplicate_devices",
                "unknown_devices",
                "unassigned_devices",
            ],
            "properties": {
                "stage1_unique_assignment_ok": {"type": "boolean"},
                "stage2_role_membership_ok": {"type": "boolean"},
                "all_devices_known": {"type": "boolean"},
                "duplicate_devices": {"type": "array", "items": {"type": "string"}},
                "unknown_devices": {"type": "array", "items": {"type": "string"}},
                "unassigned_devices": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


class SchemaValidationError(ValueError):
    """Raised when output data does not satisfy expected structure constraints."""


def canonical_substructure_type(base_type: str, modifiers: Iterable[str]) -> str:
    modifier_set = set(modifiers)

    if base_type == "differential_pair":
        return "Differential pair"
    if base_type == "current_source":
        if "cascode" in modifier_set:
            return "Cascode current source"
        if "tail" in modifier_set:
            return "Tail current source"
        if "reference" in modifier_set:
            return "Reference current source"
        if "bias" in modifier_set:
            return "Bias current source"
        return "Current source"
    if base_type == "current_mirror":
        if "cascode" in modifier_set:
            return "Cascode current mirror"
        return "Current mirror"
    if base_type == "gain_stage":
        if "folded" in modifier_set and "cascode" in modifier_set:
            return "Folded cascode"
        if "common_gate" in modifier_set:
            return "Common-gate stage"
        if "common_source" in modifier_set:
            return "Common-source stage"
        if "cascode" in modifier_set:
            return "Cascode"
        return "Gain stage"
    if base_type == "source_follower":
        return "Source follower"
    if base_type == "resistor_divider":
        return "Resistor divider"
    if base_type == "miller_compensation":
        return "Miller compensation"
    if base_type == "capacitive_feedback_network":
        return "Capacitive feedback network"
    if base_type == "cross_coupled_pair":
        return "Cross-coupled pair"
    if base_type == "diode_connected_device":
        return "Diode-connected device"

    raise SchemaValidationError(f"Unknown base_type '{base_type}'.")


def _require_dict(payload: Any, context: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaValidationError(f"{context} must be a JSON object.")
    return payload


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field} must be a non-empty string.")
    return value.strip()


def _require_list(value: Any, field: str) -> List[Any]:
    if not isinstance(value, list):
        raise SchemaValidationError(f"{field} must be a list.")
    return value


def _all_strings(values: Iterable[Any], field: str) -> List[str]:
    items = list(values)
    bad = [item for item in items if not isinstance(item, str) or not item.strip()]
    if bad:
        raise SchemaValidationError(f"{field} must contain only non-empty strings.")
    return [item.strip() for item in items]


def _normalize_modifier(modifier: str, field: str) -> str:
    normalized = modifier.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in CANONICAL_MODIFIERS:
        raise SchemaValidationError(
            f"{field} modifier '{modifier}' is not one of {CANONICAL_MODIFIERS}."
        )
    return normalized


def _infer_substructure_identity(sub_obj: Dict[str, Any], field: str) -> Tuple[str, List[str]]:
    raw_base = sub_obj.get("base_type")
    raw_modifiers = sub_obj.get("modifiers")
    raw_type = sub_obj.get("type")

    base_type: str | None = None
    modifiers: List[str] = []

    if isinstance(raw_base, str) and raw_base.strip():
        candidate = raw_base.strip().lower()
        if candidate not in CANONICAL_BASE_TYPES:
            raise SchemaValidationError(
                f"{field}.base_type '{raw_base}' is not one of {CANONICAL_BASE_TYPES}."
            )
        base_type = candidate

    if raw_modifiers is not None:
        modifier_values = _require_list(raw_modifiers, f"{field}.modifiers")
        modifiers = []
        for midx, modifier in enumerate(modifier_values):
            if not isinstance(modifier, str) or not modifier.strip():
                raise SchemaValidationError(
                    f"{field}.modifiers[{midx}] must be a non-empty string."
                )
            normalized_modifier = _normalize_modifier(modifier, f"{field}.modifiers[{midx}]")
            if normalized_modifier not in modifiers:
                modifiers.append(normalized_modifier)

    if base_type is None:
        label = _require_str(raw_type, f"{field}.type")
        alias = LEGACY_TYPE_ALIASES.get(label.lower())
        if alias is None:
            raise SchemaValidationError(
                f"{field}.type '{label}' is not recognized. Allowed canonical types: {CANONICAL_SUBSTRUCTURE_TYPES}."
            )
        inferred_base, inferred_modifiers = alias
        base_type = inferred_base
        if not modifiers:
            modifiers = list(inferred_modifiers)

    if base_type is None:
        raise SchemaValidationError(f"{field} could not determine base_type.")

    if raw_type is not None and isinstance(raw_type, str) and raw_type.strip():
        label = raw_type.strip()
        alias = LEGACY_TYPE_ALIASES.get(label.lower())
        if alias is not None:
            inferred_base, inferred_modifiers = alias
            if inferred_base != base_type:
                raise SchemaValidationError(
                    f"{field}.type '{label}' conflicts with base_type '{base_type}'."
                )
            if not modifiers:
                modifiers = list(inferred_modifiers)

    if len(modifiers) != len(set(modifiers)):
        raise SchemaValidationError(f"{field}.modifiers must not contain duplicates.")

    if "common_gate" in modifiers and "common_source" in modifiers:
        raise SchemaValidationError(
            f"{field}.modifiers cannot contain both common_gate and common_source."
        )
    if base_type != "gain_stage":
        illegal = {"common_gate", "common_source", "folded"}.intersection(modifiers)
        if illegal:
            raise SchemaValidationError(
                f"{field}.modifiers {sorted(illegal)} require base_type 'gain_stage'."
            )
    if base_type != "current_source":
        illegal = {"tail", "reference", "bias"}.intersection(modifiers)
        if illegal:
            raise SchemaValidationError(
                f"{field}.modifiers {sorted(illegal)} require base_type 'current_source'."
            )

    return base_type, modifiers


def _normalize_substructure(sub_obj: Dict[str, Any], field: str) -> Dict[str, Any]:
    base_type, modifiers = _infer_substructure_identity(sub_obj, field)
    canonical_type = canonical_substructure_type(base_type, modifiers)

    devices = _all_strings(
        _require_list(sub_obj.get("devices"), f"{field}.devices"),
        f"{field}.devices",
    )
    evidence = _require_str(sub_obj.get("evidence"), f"{field}.evidence")

    confidence = sub_obj.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0.0 or confidence > 1.0:
        raise SchemaValidationError(f"{field}.confidence must be in [0, 1].")

    variables = sub_obj.get("variables")
    if not isinstance(variables, list):
        raise SchemaValidationError(f"{field}.variables must be a list.")

    normalized_variables: List[Dict[str, Any]] = []
    for vidx, variable in enumerate(variables):
        if not isinstance(variable, dict):
            raise SchemaValidationError(f"{field}.variables[{vidx}] must be an object.")
        device = _require_str(variable.get("device"), f"{field}.variables[{vidx}].device")
        design_variables = _all_strings(
            _require_list(
                variable.get("design_variables"),
                f"{field}.variables[{vidx}].design_variables",
            ),
            f"{field}.variables[{vidx}].design_variables",
        )
        if device not in devices:
            raise SchemaValidationError(
                f"{field}.variables[{vidx}].device must belong to substructure devices."
            )
        normalized_variables.append(
            {
                "device": device,
                "design_variables": design_variables,
            }
        )

    return {
        "type": canonical_type,
        "base_type": base_type,
        "modifiers": modifiers,
        "devices": devices,
        "evidence": evidence,
        "confidence": float(confidence),
        "variables": normalized_variables,
    }


def validate_step1_payload(payload: Any) -> Dict[str, Any]:
    data = _require_dict(payload, "stage1")
    roles = _require_list(data.get("functional_roles"), "stage1.functional_roles")

    normalized_roles: List[Dict[str, Any]] = []
    for idx, role in enumerate(roles):
        role_obj = _require_dict(role, f"stage1.functional_roles[{idx}]")
        normalized_roles.append(
            {
                "name": _require_str(role_obj.get("name"), f"stage1.functional_roles[{idx}].name"),
                "devices": _all_strings(
                    _require_list(
                        role_obj.get("devices"),
                        f"stage1.functional_roles[{idx}].devices",
                    ),
                    f"stage1.functional_roles[{idx}].devices",
                ),
                "description": _require_str(
                    role_obj.get("description"),
                    f"stage1.functional_roles[{idx}].description",
                ),
            }
        )

    return {"functional_roles": normalized_roles}


def validate_step2_payload(payload: Any) -> Dict[str, Any]:
    data = _require_dict(payload, "stage2")
    roles = _require_list(data.get("roles"), "stage2.roles")

    normalized_roles: List[Dict[str, Any]] = []
    for ridx, role in enumerate(roles):
        role_obj = _require_dict(role, f"stage2.roles[{ridx}]")
        role_name = _require_str(role_obj.get("name"), f"stage2.roles[{ridx}].name")
        substructures = _require_list(
            role_obj.get("substructures"), f"stage2.roles[{ridx}].substructures"
        )

        normalized_substructures: List[Dict[str, Any]] = []
        for sidx, sub in enumerate(substructures):
            sub_obj = _require_dict(sub, f"stage2.roles[{ridx}].substructures[{sidx}]")
            normalized_substructures.append(
                _normalize_substructure(sub_obj, f"stage2.roles[{ridx}].substructures[{sidx}]")
            )

        normalized_roles.append({"name": role_name, "substructures": normalized_substructures})

    return {"roles": normalized_roles}


def validate_final_output(payload: Any) -> Dict[str, Any]:
    data = _require_dict(payload, "final output")
    schema_version = _require_str(data.get("schema_version"), "schema_version")

    tool = _require_dict(data.get("tool"), "tool")
    normalized_tool = {
        "name": _require_str(tool.get("name"), "tool.name"),
        "provider": _require_str(tool.get("provider"), "tool.provider"),
        "model": _require_str(tool.get("model"), "tool.model"),
        "generated_at_utc": _require_str(tool.get("generated_at_utc"), "tool.generated_at_utc"),
    }

    input_obj = _require_dict(data.get("input"), "input")
    netlist_path = _require_str(input_obj.get("netlist_path"), "input.netlist_path")
    subckt_name = input_obj.get("subckt_name")
    if not isinstance(subckt_name, str):
        raise SchemaValidationError("input.subckt_name must be a string.")
    device_count = input_obj.get("device_count")
    if not isinstance(device_count, int) or device_count < 0:
        raise SchemaValidationError("input.device_count must be a non-negative integer.")

    normalized_stage1 = validate_step1_payload(data.get("stage1"))
    normalized_stage2 = validate_step2_payload(data.get("stage2"))

    validation = _require_dict(data.get("validation"), "validation")
    normalized_validation: Dict[str, Any] = {}
    for field in (
        "stage1_unique_assignment_ok",
        "stage2_role_membership_ok",
        "all_devices_known",
    ):
        value = validation.get(field)
        if not isinstance(value, bool):
            raise SchemaValidationError(f"validation.{field} must be boolean.")
        normalized_validation[field] = value

    for field in ("duplicate_devices", "unknown_devices", "unassigned_devices"):
        normalized_validation[field] = _all_strings(
            _require_list(validation.get(field), f"validation.{field}"),
            f"validation.{field}",
        )

    return {
        "schema_version": schema_version,
        "tool": normalized_tool,
        "input": {
            "netlist_path": netlist_path,
            "subckt_name": subckt_name,
            "device_count": device_count,
        },
        "stage1": normalized_stage1,
        "stage2": normalized_stage2,
        "validation": normalized_validation,
    }
