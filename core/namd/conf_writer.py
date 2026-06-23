from __future__ import annotations

import os

from core.namd.models import Stage, SystemConfig


def parse_cell_file(path: str) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    lines = []
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(("cellBasisVector", "cellOrigin")):
                lines.append(stripped)
    return lines


def write_stage_conf(
    system: SystemConfig,
    stage: Stage,
    index: int,
    previous_prefix: str | None,
    conf_dir: str,
    system_dir: str = "../system",
    output_dir: str = "../output",
) -> str:
    os.makedirs(conf_dir, exist_ok=True)
    prefix = stage.output_prefix(index)
    conf_path = os.path.join(conf_dir, prefix + ".conf")
    with open(conf_path, "w") as f:
        f.write(stage_conf_text(system, stage, index, previous_prefix,
                                system_dir, output_dir))
    return conf_path


def stage_conf_text(
    system: SystemConfig,
    stage: Stage,
    index: int,
    previous_prefix: str | None,
    system_dir: str = "../system",
    output_dir: str = "../output",
) -> str:
    prefix = stage.output_prefix(index)
    out_prefix = f"{output_dir}/{prefix}"
    ff = system.forcefield
    pme = system.pme
    langevin = system.langevin
    barostat = system.barostat

    psf = f"{system_dir}/{os.path.basename(system.psf)}"
    pdb = f"{system_dir}/{os.path.basename(system.pdb)}"
    parameter_lines = [
        f'parameters          "{system_dir}/{os.path.basename(path)}"'
        for path in system.parameter_files
    ]
    cell_lines = parse_cell_file(system.cell_file)

    lines = [
        f"# easyNAMD generated NAMD config: {prefix}",
        "",
        "# Structure and force field",
        f'structure           "{psf}"',
    ]

    if _has_explicit_stage_restart(stage):
        lines += [
            f'binCoordinates      "{system_dir}/{os.path.basename(stage.restart_coordinates)}"',
            f'binVelocities       "{system_dir}/{os.path.basename(stage.restart_velocities)}"',
            f'extendedSystem      "{system_dir}/{os.path.basename(stage.restart_xsc)}"',
        ]
    elif previous_prefix:
        prev = previous_prefix if "/" in previous_prefix else f"{output_dir}/{previous_prefix}"
        lines += [
            f'binCoordinates      "{prev}.restart.coor"',
            f'binVelocities       "{prev}.restart.vel"',
            f'extendedSystem      "{prev}.restart.xsc"',
        ]
    else:
        lines += [
            f'coordinates         "{pdb}"',
        ]
        if stage.stage_type != "minimize":
            lines.append(f"temperature         {stage.temperature:g}")

    lines += [
        f"paraTypeCharmm      {'on' if ff.para_type_charmm else 'off'}",
        *parameter_lines,
    ]
    if system.first_timestep > 0:
        lines.append(f"firstTimestep       {system.first_timestep}")
    lines += ["", "# Periodic cell"]
    lines += cell_lines or [
        "# cellBasisVector* / cellOrigin were not found; fill them before NPT/PME runs",
    ]

    lines += [
        "",
        "# Integrator",
        f"timestep            {stage.timestep:g}",
        f"rigidBonds          {ff.rigid_bonds}",
        f"useSettle           {_on(ff.use_settle)}",
        f"nonbondedFreq       {ff.nonbonded_freq}",
        f"fullElectFrequency  {ff.full_elect_frequency}",
        f"stepspercycle       {ff.steps_per_cycle}",
        f"pairlistsPerCycle   {ff.pairlists_per_cycle}",
        "",
        "# NAMD 3 GPU-resident mode",
        f"CUDASOAintegrate    {_cuda_soa_value(ff.cuda_soa_integrate, stage)}",
        *([f"DeviceMigration     {ff.device_migration}"] if ff.device_migration != "off" else []),
        "",
        "# Nonbonded interactions",
        f"exclude             {ff.exclude}",
        f"1-4scaling          {ff.one_four_scaling:g}",
        f"cutoff              {ff.cutoff:g}",
        f"switching           {_on(ff.switching)}",
        f"switchdist          {ff.switchdist:g}",
        f"pairlistdist        {ff.pairlistdist:g}",
        f"margin              {ff.margin:g}",
        f"vdwForceSwitching   {_on(ff.vdw_force_switching)}",
        "",
        "# PME",
        f"PME                 {_on(pme.enabled)}",
    ]
    if pme.enabled:
        lines.append(f"PMEGridSpacing      {pme.grid_spacing:g}")

    temperature_control = _uses_temperature_control(stage)
    lines += [
        "",
        "# Temperature control",
        f"langevin            {_on(langevin.enabled and temperature_control)}",
    ]
    if langevin.enabled and temperature_control:
        lines += [
            f"langevinDamping     {langevin.damping:g}",
            f"langevinTemp        {stage.temperature:g}",
            f"langevinHydrogen    {_on(langevin.hydrogen)}",
        ]

    if stage.temperature_ramp and stage.stage_type == "md":
        lines += [
            "",
            "# Heating ramp",
            f"reassignFreq        {stage.ramp_freq}",
            f"reassignTemp        {stage.ramp_start:g}",
            f"reassignIncr        {stage.ramp_increment:g}",
            f"reassignHold        {stage.ramp_end:g}",
        ]

    pressure = _pressure_settings(system, stage)

    lines += ["", "# Pressure control"]
    if pressure["enabled"]:
        lines += [
            "langevinPiston      on",
            f"langevinPistonTarget {stage.pressure:g}",
            f"langevinPistonPeriod {barostat.piston_period:g}",
            f"langevinPistonDecay {barostat.piston_decay:g}",
            f"langevinPistonTemp  {stage.temperature:g}",
            f"useGroupPressure    {_on(pressure['use_group_pressure'])}",
            f"useFlexibleCell     {_on(pressure['use_flexible_cell'])}",
            f"useConstantArea     {_on(pressure['use_constant_area'])}",
        ]
        if pressure["mode"] == "surface_tension":
            lines.append(f"surfaceTensionTarget {pressure['surface_tension_target']:g}")
    else:
        lines.append("langevinPiston      off")

    lines += [
        "",
        "# Wrapping",
        f"wrapAll             {_on(ff.wrap_all)}",
        f"wrapWater           {_on(ff.wrap_water)}",
        f"wrapNearest         {_on(ff.wrap_nearest)}",
        "",
        "# Output",
        f'outputName          "{out_prefix}"',
        f'binaryoutput        {_on(ff.binary_output)}',
        f'binaryrestart       {_on(ff.binary_restart)}',
        f"restartfreq         {stage.output.restart_freq}",
        f'dcdfile             "{out_prefix}.dcd"',
        f"dcdfreq             {stage.output.dcd_freq}",
        f'xstFreq             {stage.output.xst_freq}',
        f"outputEnergies      {stage.output.output_energies}",
        f"outputTiming        {stage.output.output_timing}",
    ]

    if stage.restraints.enabled and stage.restraints.reference_pdb:
        reference = stage.restraints.reference_pdb
        reference_name = os.path.basename(reference) if reference else "restraints_NOT_GENERATED.pdb"
        lines += [
            "",
            "# Positional restraints",
            "constraints         on",
            f'consref             "{system_dir}/{reference_name}"',
            f'conskfile           "{system_dir}/{reference_name}"',
            f"conskcol            {stage.restraints.column}",
            f"# selection: {stage.restraints.selection}",
            f"# default force constant for generated restraint PDB: {stage.restraints.force_constant:g}",
        ]
    else:
        lines += ["", "constraints         off"]
        if stage.restraints.force_constant > 0.0:
            lines += [
                f"# Positional restraint requested: selection '{stage.restraints.selection}', "
                f"k={stage.restraints.force_constant:g}.",
                "# A restraint reference PDB was not provided, so constraints are off.",
            ]

    if stage.custom_lines:
        lines += ["", "# Custom user lines", *stage.custom_lines]

    lines += ["", "# Run"]
    if stage.stage_type == "minimize":
        lines.append(f"minimize            {stage.minimize_steps}")
    else:
        lines.append(f"run                 {stage.steps}")

    return "\n".join(lines) + "\n"


def _on(value: bool) -> str:
    return "on" if value else "off"


def _has_explicit_stage_restart(stage: Stage) -> bool:
    return bool(stage.restart_coordinates and stage.restart_velocities and stage.restart_xsc)


def _cuda_soa_value(mode: str, stage: Stage) -> str:
    mode = (mode or "auto").lower()
    if mode in ("on", "off"):
        return mode
    if stage.stage_type == "minimize":
        return "off"
    return "on"


def _uses_temperature_control(stage: Stage) -> bool:
    return stage.stage_type == "md" and stage.ensemble in ("NVT", "NPT", "NPAT", "NPgT")


def _pressure_settings(system: SystemConfig, stage: Stage) -> dict[str, bool | float | str]:
    mode = (stage.pressure_control.mode or "auto").lower()
    use_global_defaults = mode == "auto"
    if stage.stage_type != "md" or stage.ensemble in ("NVE", "NVT"):
        mode = "off"
    if mode == "auto":
        mode = _legacy_pressure_mode(system, stage)

    enabled = mode in ("isotropic", "semiisotropic", "npat", "surface_tension")
    use_group_pressure = (
        system.barostat.use_group_pressure
        if use_global_defaults else stage.pressure_control.use_group_pressure
    )
    use_flexible_cell = (
        system.barostat.use_flexible_cell
        if use_global_defaults else stage.pressure_control.use_flexible_cell
    )
    use_constant_area = (
        system.barostat.use_constant_area
        if use_global_defaults else stage.pressure_control.use_constant_area
    )
    surface_tension_target = stage.pressure_control.surface_tension_target
    if surface_tension_target == 0.0:
        surface_tension_target = system.barostat.surface_tension_target

    if mode == "isotropic":
        use_flexible_cell = False
        use_constant_area = False
    elif mode == "semiisotropic":
        use_flexible_cell = True
        use_constant_area = False
    elif mode == "npat":
        use_flexible_cell = False
        use_constant_area = True
    elif mode == "surface_tension":
        use_flexible_cell = True
        use_constant_area = False

    return {
        "mode": mode,
        "enabled": enabled,
        "use_group_pressure": use_group_pressure,
        "use_flexible_cell": use_flexible_cell,
        "use_constant_area": use_constant_area,
        "surface_tension_target": surface_tension_target,
    }


def _legacy_pressure_mode(system: SystemConfig, stage: Stage) -> str:
    if stage.ensemble == "NPAT":
        return "npat"
    if stage.ensemble == "NPgT":
        return "surface_tension"
    if stage.ensemble == "NPT" and system.system_type == "membrane":
        return "semiisotropic"
    if stage.ensemble == "NPT":
        return "isotropic"
    return "off"
