from agentic_sizing import MockSimulationAdapter


design = {"gm1": 1.2, "gm2": 1.0, "rout": 8.0, "cc": 1.0, "ibias": 1.0}
print(MockSimulationAdapter().simulate(design))
