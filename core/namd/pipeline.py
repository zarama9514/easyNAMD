from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field

from core.namd.models import OutputConfig, RestraintConfig, Stage, dataclass_from_dict


@dataclass
class Pipeline:
    name: str = "Standard protein MD"
    stages: list[Stage] = field(default_factory=list)

    def enabled_stages(self) -> list[Stage]:
        return [s for s in self.stages if s.enabled]

    def expanded_stages(self) -> list[Stage]:
        """Return enabled stages with chunked MD stages expanded."""
        expanded: list[Stage] = []
        for stage in self.enabled_stages():
            stage.sync_steps_from_duration()
            chunks = max(1, int(stage.chunk_count))
            if stage.stage_type != "md" or chunks == 1:
                expanded.append(deepcopy(stage))
                continue
            base_steps = stage.steps // chunks
            remainder = stage.steps % chunks
            for i in range(chunks):
                chunk = deepcopy(stage)
                chunk.chunk_count = 1
                chunk.steps = base_steps + (1 if i < remainder else 0)
                chunk.duration_value = chunk.steps * chunk.timestep / 1_000_000.0
                chunk.duration_unit = "ns"
                chunk.name = f"{stage.name}_{i + 1:02d}"
                if i > 0:
                    chunk.temperature_ramp = False
                expanded.append(chunk)
        return expanded

    def total_steps(self) -> int:
        return sum(stage.step_count() for stage in self.expanded_stages())

    def total_duration_ns(self) -> float:
        return sum(stage.duration_ps() for stage in self.expanded_stages()) / 1000.0

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "name": self.name,
            "stages": [s.__dict__ | {
                "restraints": s.restraints.__dict__,
                "output": s.output.__dict__,
            } for s in self.stages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pipeline":
        return cls(
            name=data.get("name", "NAMD pipeline"),
            stages=[dataclass_from_dict(Stage, item)
                    for item in data.get("stages", [])],
        )

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Pipeline":
        with open(path) as f:
            return cls.from_dict(json.load(f))


def _restraint(k: float, selection: str = "protein and backbone") -> RestraintConfig:
    return RestraintConfig(
        enabled=k > 0.0,
        selection=selection,
        force_constant=k,
    )


def _out() -> OutputConfig:
    return OutputConfig()


def _md_stage(name: str, ensemble: str, ns: float, k: float = 0.0,
              temperature: float = 310.0, chunks: int = 1,
              ramp: bool = False) -> Stage:
    stage = Stage(
        name=name,
        stage_type="md",
        ensemble=ensemble,
        duration_value=ns,
        duration_unit="ns",
        timestep=2.0,
        temperature=temperature,
        temperature_ramp=ramp,
        ramp_start=0.0,
        ramp_end=temperature,
        restraints=_restraint(k),
        output=_out(),
        chunk_count=chunks,
    )
    stage.sync_steps_from_duration()
    return stage


def default_pipeline() -> Pipeline:
    return Pipeline(
        name="Standard protein in water",
        stages=[
            Stage(
                name="minimize",
                stage_type="minimize",
                ensemble="NVT",
                minimize_steps=10000,
                restraints=_restraint(5.0),
                output=_out(),
            ),
            _md_stage("heat", "NVT", ns=0.124, k=5.0, ramp=True),
            _md_stage("eq_npt_restraint_5", "NPT", ns=0.5, k=5.0),
            _md_stage("eq_npt_restraint_1", "NPT", ns=0.5, k=1.0),
            _md_stage("eq_npt_free", "NPT", ns=0.5, k=0.0),
            _md_stage("production", "NPT", ns=10.0, k=0.0),
        ],
    )


def quick_test_pipeline() -> Pipeline:
    return Pipeline(
        name="Quick smoke test",
        stages=[
            Stage(name="minimize_test", stage_type="minimize", minimize_steps=1000),
            _md_stage("nvt_test", "NVT", ns=0.01),
        ],
    )


def cautious_equilibration_pipeline() -> Pipeline:
    return Pipeline(
        name="Cautious equilibration",
        stages=[
            Stage(name="minimize_restrained", stage_type="minimize",
                  minimize_steps=20000, restraints=_restraint(10.0), output=_out()),
            _md_stage("heat_slow", "NVT", ns=0.25, k=10.0, ramp=True),
            _md_stage("eq_npt_k10", "NPT", ns=0.5, k=10.0),
            _md_stage("eq_npt_k5", "NPT", ns=0.5, k=5.0),
            _md_stage("eq_npt_k2", "NPT", ns=0.5, k=2.0),
            _md_stage("eq_npt_k1", "NPT", ns=0.5, k=1.0),
            _md_stage("eq_npt_free", "NPT", ns=1.0, k=0.0),
        ],
    )


def production_only_pipeline() -> Pipeline:
    return Pipeline(
        name="Production only from restart",
        stages=[
            _md_stage("production", "NPT", ns=10.0, chunks=1),
        ],
    )


def chunked_production_pipeline() -> Pipeline:
    return Pipeline(
        name="Chunked production 100 ns",
        stages=[
            _md_stage("production", "NPT", ns=100.0, chunks=10),
        ],
    )


def template_library() -> dict[str, Pipeline]:
    return {
        "Standard protein in water": default_pipeline(),
        "Quick smoke test": quick_test_pipeline(),
        "Cautious equilibration": cautious_equilibration_pipeline(),
        "Production only from restart": production_only_pipeline(),
        "Chunked production 100 ns": chunked_production_pipeline(),
    }
