from pathlib import Path

from agentic_sizing import MockSimulationAdapter, RunConfig


def test_run_config_uses_correct_record_spelling(tmp_path: Path) -> None:
    config = RunConfig(netlist_path="example.sp", kb_root="kb", output_dir=tmp_path)
    assert config.simulation_record_path == tmp_path / "simulation_record.json"


def test_mock_simulator_is_deterministic() -> None:
    design = {"gm1": 1.2, "gm2": 1.0, "rout": 8.0, "cc": 1.0, "ibias": 1.0}
    adapter = MockSimulationAdapter()
    assert adapter.simulate(design) == adapter.simulate(design)
