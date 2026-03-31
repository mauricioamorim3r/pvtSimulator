from __future__ import annotations

import math

import pandas as pd

from .models import BackendStatus, CompositionScenario

STD_REFERENCE_TEMPERATURE_C = 20.0
STD_REFERENCE_PRESSURE_BARA = 1.01325


def detect_neqsim_backend() -> BackendStatus:
    try:
        from neqsim.thermo import fluid  # noqa: F401
    except Exception as exc:
        return BackendStatus(
            available=False,
            mode='shadow',
            detail=f'NeqSim unavailable in this environment: {exc}',
        )
    return BackendStatus(available=True, mode='neqsim', detail='NeqSim backend available.')


def _estimate_separator_oil_density(scenario: CompositionScenario) -> float:
    heavy_fraction = scenario.heavy_fraction
    plus_density = scenario.plus_density_g_cc or 0.88
    return 620.0 + heavy_fraction * 320.0 + (plus_density - 0.82) * 900.0


def _estimate_live_gas_density(scenario: CompositionScenario, pressure_bara: float, temperature_c: float) -> float:
    mw = scenario.mixture_mw_g_mol / 1000.0
    pressure_pa = max(pressure_bara, 1.01325) * 1e5
    temperature_k = temperature_c + 273.15
    z_factor = max(0.72, 1.0 - 0.00065 * pressure_bara + 0.0002 * max(temperature_c, 0.0))
    return pressure_pa * mw / (z_factor * 8.314462618 * temperature_k)


def _calc_standard_gor_sm3_sm3(phase) -> float:
    return (
        phase.getNumberOfMolesInPhase()
        * 8.314462618
        * 288.15
        / 101325.0
    )


def _build_neqsim_fluid(scenario: CompositionScenario):
    from neqsim.thermo import fluid

    thermo = fluid('srk-peneloux')
    component_map = {
        'N2': 'nitrogen',
        'CO2': 'CO2',
        'C1': 'methane',
        'C2': 'ethane',
        'C3': 'propane',
        'I-C4': 'i-butane',
        'N-C4': 'n-butane',
        'I-C5': 'i-pentane',
        'N-C5': 'n-pentane',
        'C6': 'n-hexane',
        'C7': 'n-heptane',
        'C8': 'n-octane',
        'C9': 'n-nonane',
    }

    for component, fraction in scenario.components_mol_pct.items():
        if fraction is None or fraction <= 0.0:
            continue
        if component == 'C10+':
            thermo.addPlusFraction(
                'C10',
                float(fraction),
                (scenario.plus_mw_g_mol or 280.0) / 1000.0,
                scenario.plus_density_g_cc or 0.88,
            )
        else:
            thermo.addComponent(component_map[component], float(fraction))

    thermo.createDatabase(True)
    thermo.setMixingRule(2)
    thermo.setMultiPhaseCheck(True)
    thermo.useVolumeCorrection(True)
    return thermo


def _phase_snapshot(system) -> dict[str, float]:
    system.initPhysicalProperties()
    total_mass = system.getMass('kg')
    snapshot: dict[str, float] = {
        'total_mass_kg': total_mass,
        'oil_mass_kg': 0.0,
        'gas_mass_kg': 0.0,
        'oil_density_kgm3': math.nan,
        'gas_density_kgm3': math.nan,
        'oil_volume_m3': math.nan,
        'gas_volume_m3': math.nan,
        'std_gor_sm3_sm3': math.nan,
        'actual_gor_m3_m3': math.nan,
    }

    if system.hasPhaseType('oil'):
        oil = system.getPhase('oil')
        snapshot['oil_mass_kg'] = oil.getMass()
        snapshot['oil_density_kgm3'] = oil.getDensity('kg/m3')
        snapshot['oil_volume_m3'] = oil.getVolume('m3')

    if system.hasPhaseType('gas'):
        gas = system.getPhase('gas')
        snapshot['gas_mass_kg'] = gas.getMass()
        snapshot['gas_density_kgm3'] = gas.getDensity('kg/m3')
        snapshot['gas_volume_m3'] = gas.getVolume('m3')

    if (
        system.hasPhaseType('oil')
        and system.hasPhaseType('gas')
        and snapshot['oil_volume_m3']
        and not math.isnan(snapshot['oil_volume_m3'])
    ):
        snapshot['std_gor_sm3_sm3'] = _calc_standard_gor_sm3_sm3(system.getPhase('gas')) / snapshot['oil_volume_m3']
        snapshot['actual_gor_m3_m3'] = snapshot['gas_volume_m3'] / snapshot['oil_volume_m3']

    return snapshot


def _calc_fe_rs_20c_1atm(
    separator_system,
    separator_snapshot: dict[str, float],
    measured_separator_oil_kgph: float,
) -> dict[str, float]:
    from neqsim.thermo import TPflash

    result = {
        'separator_oil_volume_derived_m3ph': math.nan,
        'std_oil_volume_20c_1atm_m3ph': math.nan,
        'std_gas_from_separator_oil_20c_1atm_sm3ph': math.nan,
        'fe_20c_1atm': math.nan,
        'rs_20c_1atm_sm3_sm3': math.nan,
    }

    if not separator_system.hasPhaseType('oil'):
        return result

    separator_oil_mass_model = float(separator_snapshot.get('oil_mass_kg') or 0.0)
    separator_oil_volume_model = separator_snapshot.get('oil_volume_m3')
    if (
        separator_oil_mass_model <= 0.0
        or separator_oil_volume_model is None
        or math.isnan(separator_oil_volume_model)
        or separator_oil_volume_model <= 0.0
    ):
        return result

    std_oil_system = separator_system.phaseToSystem('oil')
    std_oil_system.setTemperature(STD_REFERENCE_TEMPERATURE_C, 'C')
    std_oil_system.setPressure(STD_REFERENCE_PRESSURE_BARA, 'bara')
    TPflash(std_oil_system)
    std_snapshot = _phase_snapshot(std_oil_system)

    std_oil_volume = std_snapshot.get('oil_volume_m3')
    std_gas_volume = std_snapshot.get('gas_volume_m3')
    std_gas_volume = 0.0 if std_gas_volume is None or math.isnan(std_gas_volume) else std_gas_volume

    if std_oil_volume is None or math.isnan(std_oil_volume) or std_oil_volume <= 0.0:
        return result

    oil_scale_factor = (
        measured_separator_oil_kgph / separator_oil_mass_model
        if measured_separator_oil_kgph > 0.0
        else math.nan
    )
    if oil_scale_factor == oil_scale_factor:
        result['separator_oil_volume_derived_m3ph'] = separator_oil_volume_model * oil_scale_factor
        result['std_oil_volume_20c_1atm_m3ph'] = std_oil_volume * oil_scale_factor
        result['std_gas_from_separator_oil_20c_1atm_sm3ph'] = std_gas_volume * oil_scale_factor

    result['fe_20c_1atm'] = std_oil_volume / separator_oil_volume_model
    result['rs_20c_1atm_sm3_sm3'] = std_gas_volume / std_oil_volume
    return result


def _resolve_mpfm_conditions(row: pd.Series, default_pressure_bara: float, default_temperature_c: float) -> tuple[float, float]:
    row_pressure = row.get('mpfm_pressure_bara')
    row_temperature = row.get('mpfm_temperature_c')
    pressure = float(row_pressure) if row_pressure == row_pressure and row_pressure is not None else default_pressure_bara
    temperature = float(row_temperature) if row_temperature == row_temperature and row_temperature is not None else default_temperature_c
    return pressure, temperature


def _shadow_backflash_row(row: pd.Series, scenario: CompositionScenario, mpfm_pressure_bara: float, mpfm_temperature_c: float) -> pd.Series:
    mpfm_pressure_bara, mpfm_temperature_c = _resolve_mpfm_conditions(row, mpfm_pressure_bara, mpfm_temperature_c)
    separator_pressure = float(row.get('separator_pressure_bara') or 86.0)
    separator_temperature = float(row.get('separator_temperature_c') or 60.0)
    oil_kgph = float(row.get('separator_oil_kgph') or 0.0)
    gas_kgph = float(row.get('separator_gas_kgph') or 0.0)
    separator_gor = row.get('separator_gor_sm3_sm3')
    separator_gor = float(separator_gor) if separator_gor == separator_gor else (scenario.estimated_gor_sm3_sm3 or 0.0)

    pressure_delta = mpfm_pressure_bara - separator_pressure
    temperature_delta = mpfm_temperature_c - separator_temperature
    heavy_fraction = scenario.heavy_fraction
    methane_fraction = scenario.normalized_components.get('C1', 0.0)
    plus_density = scenario.plus_density_g_cc or 0.88

    dissolution_index = 0.06
    dissolution_index += pressure_delta * 0.0016
    dissolution_index -= temperature_delta * 0.0009
    dissolution_index += heavy_fraction * 0.22
    dissolution_index += max(plus_density - 0.86, 0.0) * 0.35
    dissolution_index -= methane_fraction * 0.035
    dissolution_index = max(0.0, min(0.38, dissolution_index))

    gas_recombined = gas_kgph * dissolution_index
    backflash_oil_kgph = oil_kgph + gas_recombined
    backflash_gas_kgph = max(gas_kgph - gas_recombined, 0.0)

    k_oil = backflash_oil_kgph / oil_kgph if oil_kgph else math.nan
    k_gas = backflash_gas_kgph / gas_kgph if gas_kgph else math.nan

    oil_density_separator = _estimate_separator_oil_density(scenario)
    oil_density_live = oil_density_separator * (1.0 + pressure_delta * 0.00085 - temperature_delta * 0.0005)
    oil_density_live = max(oil_density_separator * 0.8, oil_density_live)
    gas_density_live = _estimate_live_gas_density(scenario, mpfm_pressure_bara, mpfm_temperature_c)

    backflash_gor = separator_gor
    if oil_kgph > 0.0 and gas_kgph > 0.0:
        backflash_gor *= (backflash_gas_kgph / gas_kgph) / max(backflash_oil_kgph / oil_kgph, 1e-6)

    result = row.copy()
    result['backend_mode'] = 'shadow'
    result['mpfm_pressure_bara'] = mpfm_pressure_bara
    result['mpfm_temperature_c'] = mpfm_temperature_c
    result['backflash_oil_kgph'] = backflash_oil_kgph
    result['backflash_gas_kgph'] = backflash_gas_kgph
    result['k_oil'] = k_oil
    result['k_gas'] = k_gas
    result['live_oil_density_kgm3'] = oil_density_live
    result['live_gas_density_kgm3'] = gas_density_live
    result['backflash_gor_sm3_sm3'] = backflash_gor
    result['std_reference_temperature_c'] = STD_REFERENCE_TEMPERATURE_C
    result['std_reference_pressure_bara'] = STD_REFERENCE_PRESSURE_BARA
    result['separator_oil_volume_derived_m3ph'] = math.nan
    result['std_oil_volume_20c_1atm_m3ph'] = math.nan
    result['std_gas_from_separator_oil_20c_1atm_sm3ph'] = math.nan
    result['fe_20c_1atm'] = math.nan
    result['rs_20c_1atm_sm3_sm3'] = math.nan
    result['measured_separator_oil_volume_m3ph'] = row.get('separator_oil_volume_m3ph')
    result['measured_separator_oil_density_kgm3'] = row.get('separator_oil_density_kgm3')
    result['separator_oil_density_error_pct'] = math.nan
    result['separator_oil_volume_error_pct'] = math.nan

    fcs_oil = row.get('fcs320_oil_kgph')
    fcs_gas = row.get('fcs320_gas_kgph')
    fcs_gor = row.get('fcs320_gor_sm3_sm3')
    result['fcs320_k_oil'] = float(fcs_oil) / oil_kgph if fcs_oil == fcs_oil and oil_kgph else math.nan
    result['fcs320_k_gas'] = float(fcs_gas) / gas_kgph if fcs_gas == fcs_gas and gas_kgph else math.nan
    result['deviation_k_oil_pct'] = ((k_oil / result['fcs320_k_oil']) - 1.0) * 100.0 if result['fcs320_k_oil'] == result['fcs320_k_oil'] and result['fcs320_k_oil'] else math.nan
    result['deviation_k_gas_pct'] = ((k_gas / result['fcs320_k_gas']) - 1.0) * 100.0 if result['fcs320_k_gas'] == result['fcs320_k_gas'] and result['fcs320_k_gas'] else math.nan
    result['deviation_gor_pct'] = ((backflash_gor / float(fcs_gor)) - 1.0) * 100.0 if fcs_gor == fcs_gor and float(fcs_gor) else math.nan
    return result


def _run_neqsim_backflash_row(row: pd.Series, scenario: CompositionScenario, mpfm_pressure_bara: float, mpfm_temperature_c: float) -> pd.Series:
    from neqsim.thermo import TPflash

    mpfm_pressure_bara, mpfm_temperature_c = _resolve_mpfm_conditions(row, mpfm_pressure_bara, mpfm_temperature_c)
    separator_pressure = float(row.get('separator_pressure_bara') or 86.0)
    separator_temperature = float(row.get('separator_temperature_c') or 60.0)
    measured_oil_kgph = float(row.get('separator_oil_kgph') or 0.0)
    measured_gas_kgph = float(row.get('separator_gas_kgph') or 0.0)
    measured_total_kgph = float(row.get('separator_total_kgph') or (measured_oil_kgph + measured_gas_kgph))
    measured_separator_oil_volume = row.get('separator_oil_volume_m3ph')
    measured_separator_oil_density = row.get('separator_oil_density_kgm3')
    measured_separator_oil_volume = (
        float(measured_separator_oil_volume)
        if measured_separator_oil_volume == measured_separator_oil_volume and measured_separator_oil_volume is not None
        else math.nan
    )
    measured_separator_oil_density = (
        float(measured_separator_oil_density)
        if measured_separator_oil_density == measured_separator_oil_density and measured_separator_oil_density is not None
        else math.nan
    )
    if math.isnan(measured_separator_oil_volume) and measured_oil_kgph > 0.0 and measured_separator_oil_density > 0.0:
        measured_separator_oil_volume = measured_oil_kgph / measured_separator_oil_density
    if math.isnan(measured_separator_oil_density) and measured_oil_kgph > 0.0 and measured_separator_oil_volume > 0.0:
        measured_separator_oil_density = measured_oil_kgph / measured_separator_oil_volume

    separator_system = _build_neqsim_fluid(scenario)
    separator_system.setTemperature(separator_temperature, 'C')
    separator_system.setPressure(separator_pressure, 'bara')
    TPflash(separator_system)
    separator_snapshot = _phase_snapshot(separator_system)

    mpfm_system = separator_system.clone()
    mpfm_system.setTemperature(mpfm_temperature_c, 'C')
    mpfm_system.setPressure(mpfm_pressure_bara, 'bara')
    TPflash(mpfm_system)
    mpfm_snapshot = _phase_snapshot(mpfm_system)

    scale_factor = measured_total_kgph / separator_snapshot['total_mass_kg'] if separator_snapshot['total_mass_kg'] else math.nan
    predicted_separator_oil_kgph = separator_snapshot['oil_mass_kg'] * scale_factor
    predicted_separator_gas_kgph = separator_snapshot['gas_mass_kg'] * scale_factor
    backflash_oil_kgph = mpfm_snapshot['oil_mass_kg'] * scale_factor
    backflash_gas_kgph = mpfm_snapshot['gas_mass_kg'] * scale_factor
    fe_rs_snapshot = _calc_fe_rs_20c_1atm(
        separator_system=separator_system,
        separator_snapshot=separator_snapshot,
        measured_separator_oil_kgph=measured_oil_kgph,
    )

    result = row.copy()
    result['backend_mode'] = 'neqsim'
    result['mpfm_pressure_bara'] = mpfm_pressure_bara
    result['mpfm_temperature_c'] = mpfm_temperature_c
    result['predicted_separator_oil_kgph'] = predicted_separator_oil_kgph
    result['predicted_separator_gas_kgph'] = predicted_separator_gas_kgph
    result['backflash_oil_kgph'] = backflash_oil_kgph
    result['backflash_gas_kgph'] = backflash_gas_kgph
    result['k_oil'] = backflash_oil_kgph / measured_oil_kgph if measured_oil_kgph else math.nan
    result['k_gas'] = backflash_gas_kgph / measured_gas_kgph if measured_gas_kgph else math.nan
    result['model_k_oil'] = backflash_oil_kgph / predicted_separator_oil_kgph if predicted_separator_oil_kgph else math.nan
    result['model_k_gas'] = backflash_gas_kgph / predicted_separator_gas_kgph if predicted_separator_gas_kgph else math.nan
    result['live_oil_density_kgm3'] = mpfm_snapshot['oil_density_kgm3']
    result['live_gas_density_kgm3'] = mpfm_snapshot['gas_density_kgm3']
    result['separator_oil_density_kgm3'] = separator_snapshot['oil_density_kgm3']
    result['separator_gas_density_kgm3'] = separator_snapshot['gas_density_kgm3']
    result['backflash_gor_sm3_sm3'] = mpfm_snapshot['std_gor_sm3_sm3']
    result['predicted_separator_gor_sm3_sm3'] = separator_snapshot['std_gor_sm3_sm3']
    result['actual_gor_m3_m3'] = mpfm_snapshot['actual_gor_m3_m3']
    result['std_reference_temperature_c'] = STD_REFERENCE_TEMPERATURE_C
    result['std_reference_pressure_bara'] = STD_REFERENCE_PRESSURE_BARA
    result['separator_oil_volume_derived_m3ph'] = fe_rs_snapshot['separator_oil_volume_derived_m3ph']
    result['std_oil_volume_20c_1atm_m3ph'] = fe_rs_snapshot['std_oil_volume_20c_1atm_m3ph']
    result['std_gas_from_separator_oil_20c_1atm_sm3ph'] = fe_rs_snapshot['std_gas_from_separator_oil_20c_1atm_sm3ph']
    result['fe_20c_1atm'] = fe_rs_snapshot['fe_20c_1atm']
    result['rs_20c_1atm_sm3_sm3'] = fe_rs_snapshot['rs_20c_1atm_sm3_sm3']
    result['measured_separator_oil_volume_m3ph'] = measured_separator_oil_volume
    result['measured_separator_oil_density_kgm3'] = measured_separator_oil_density
    result['measured_mpfm_oil_density_kgm3'] = row.get('mpfm_oil_density_kgm3')
    result['measured_mpfm_gas_density_kgm3'] = row.get('mpfm_gas_density_kgm3')
    result['measured_mpfm_oil_kgph'] = row.get('mpfm_oil_kgph')
    result['measured_mpfm_gas_kgph'] = row.get('mpfm_gas_kgph')
    result['measured_mpfm_water_kgph'] = row.get('mpfm_water_kgph')

    result['separator_oil_model_error_pct'] = (
        ((predicted_separator_oil_kgph / measured_oil_kgph) - 1.0) * 100.0
        if measured_oil_kgph
        else math.nan
    )
    result['separator_gas_model_error_pct'] = (
        ((predicted_separator_gas_kgph / measured_gas_kgph) - 1.0) * 100.0
        if measured_gas_kgph
        else math.nan
    )
    result['separator_oil_density_error_pct'] = (
        ((result['separator_oil_density_kgm3'] / measured_separator_oil_density) - 1.0) * 100.0
        if measured_separator_oil_density == measured_separator_oil_density and measured_separator_oil_density != 0.0
        else math.nan
    )
    result['separator_oil_volume_error_pct'] = (
        ((result['separator_oil_volume_derived_m3ph'] / measured_separator_oil_volume) - 1.0) * 100.0
        if measured_separator_oil_volume == measured_separator_oil_volume and measured_separator_oil_volume != 0.0
        else math.nan
    )
    result['mpfm_oil_density_error_pct'] = (
        ((result['live_oil_density_kgm3'] / float(result['measured_mpfm_oil_density_kgm3'])) - 1.0) * 100.0
        if result['measured_mpfm_oil_density_kgm3'] == result['measured_mpfm_oil_density_kgm3'] and float(result['measured_mpfm_oil_density_kgm3']) != 0.0
        else math.nan
    )
    result['mpfm_gas_density_error_pct'] = (
        ((result['live_gas_density_kgm3'] / float(result['measured_mpfm_gas_density_kgm3'])) - 1.0) * 100.0
        if result['measured_mpfm_gas_density_kgm3'] == result['measured_mpfm_gas_density_kgm3'] and float(result['measured_mpfm_gas_density_kgm3']) != 0.0
        else math.nan
    )
    result['mpfm_oil_mass_error_pct'] = (
        ((result['backflash_oil_kgph'] / float(result['measured_mpfm_oil_kgph'])) - 1.0) * 100.0
        if result['measured_mpfm_oil_kgph'] == result['measured_mpfm_oil_kgph'] and float(result['measured_mpfm_oil_kgph']) != 0.0
        else math.nan
    )
    result['mpfm_gas_mass_error_pct'] = (
        ((result['backflash_gas_kgph'] / float(result['measured_mpfm_gas_kgph'])) - 1.0) * 100.0
        if result['measured_mpfm_gas_kgph'] == result['measured_mpfm_gas_kgph'] and float(result['measured_mpfm_gas_kgph']) != 0.0
        else math.nan
    )

    fcs_oil = row.get('fcs320_oil_kgph')
    fcs_gas = row.get('fcs320_gas_kgph')
    fcs_gor = row.get('fcs320_gor_sm3_sm3')
    result['fcs320_k_oil'] = float(fcs_oil) / measured_oil_kgph if fcs_oil == fcs_oil and measured_oil_kgph else math.nan
    result['fcs320_k_gas'] = float(fcs_gas) / measured_gas_kgph if fcs_gas == fcs_gas and measured_gas_kgph else math.nan
    result['deviation_k_oil_pct'] = ((result['k_oil'] / result['fcs320_k_oil']) - 1.0) * 100.0 if result['fcs320_k_oil'] == result['fcs320_k_oil'] and result['fcs320_k_oil'] else math.nan
    result['deviation_k_gas_pct'] = ((result['k_gas'] / result['fcs320_k_gas']) - 1.0) * 100.0 if result['fcs320_k_gas'] == result['fcs320_k_gas'] and result['fcs320_k_gas'] else math.nan
    result['deviation_gor_pct'] = ((result['backflash_gor_sm3_sm3'] / float(fcs_gor)) - 1.0) * 100.0 if fcs_gor == fcs_gor and float(fcs_gor) else math.nan
    return result


def calculate_backflash_table(
    separator_df: pd.DataFrame,
    scenario: CompositionScenario,
    mpfm_pressure_bara: float,
    mpfm_temperature_c: float,
    prefer_neqsim: bool = True,
) -> tuple[pd.DataFrame, BackendStatus]:
    backend = detect_neqsim_backend()
    use_neqsim = prefer_neqsim and backend.available

    rows = []
    for _, row in separator_df.iterrows():
        if use_neqsim:
            try:
                result_row = _run_neqsim_backflash_row(row, scenario, mpfm_pressure_bara, mpfm_temperature_c)
                result_row['scenario_key'] = scenario.key
                result_row['scenario_label'] = scenario.label
                rows.append(result_row)
                continue
            except Exception as exc:
                backend = BackendStatus(False, 'shadow', f'NeqSim fallback activated: {exc}')
                use_neqsim = False
        result_row = _shadow_backflash_row(row, scenario, mpfm_pressure_bara, mpfm_temperature_c)
        result_row['scenario_key'] = scenario.key
        result_row['scenario_label'] = scenario.label
        rows.append(result_row)

    return pd.DataFrame(rows), backend
