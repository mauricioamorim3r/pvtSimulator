from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from backflash_app import (
    calculate_backflash_table,
    detect_neqsim_backend,
    load_built_in_separator_cases,
    load_composition_catalog,
    load_separator_upload,
)


BASE_DIR = Path(__file__).resolve().parent


st.set_page_config(
    page_title='SIMULPVT Back-Flash',
    page_icon=':oil_drum:',
    layout='wide',
)


@st.cache_data
def get_catalog() -> dict:
    return load_composition_catalog(BASE_DIR)


@st.cache_data
def get_default_cases() -> pd.DataFrame:
    return load_built_in_separator_cases(BASE_DIR)


def _format_metric(value: float | None, suffix: str = '') -> str:
    if value is None or pd.isna(value):
        return '-'
    return f'{value:,.2f}{suffix}'


def _safe_abs_mean(series: pd.Series) -> float | None:
    cleaned = pd.to_numeric(series, errors='coerce').dropna()
    if cleaned.empty:
        return None
    return float(cleaned.abs().mean())


def _build_scenario_ranking(results: pd.DataFrame) -> pd.DataFrame:
    ranking_rows = []
    for scenario_key, frame in results.groupby('scenario_key', dropna=False):
        oil_density_error = _safe_abs_mean(frame.get('mpfm_oil_density_error_pct', pd.Series(dtype='float64')))
        oil_mass_error = _safe_abs_mean(frame.get('mpfm_oil_mass_error_pct', pd.Series(dtype='float64')))
        separator_density_error = _safe_abs_mean(frame.get('separator_oil_density_error_pct', pd.Series(dtype='float64')))
        separator_volume_error = _safe_abs_mean(frame.get('separator_oil_volume_error_pct', pd.Series(dtype='float64')))
        separator_oil_error = _safe_abs_mean(frame.get('separator_oil_model_error_pct', pd.Series(dtype='float64')))
        k_oil_deviation = _safe_abs_mean(frame.get('deviation_k_oil_pct', pd.Series(dtype='float64')))

        weighted_terms = []
        if oil_density_error is not None:
            weighted_terms.append(oil_density_error * 0.30)
        if oil_mass_error is not None:
            weighted_terms.append(oil_mass_error * 0.25)
        if separator_density_error is not None:
            weighted_terms.append(separator_density_error * 0.15)
        if separator_volume_error is not None:
            weighted_terms.append(separator_volume_error * 0.15)
        if separator_oil_error is not None:
            weighted_terms.append(separator_oil_error * 0.10)
        if k_oil_deviation is not None:
            weighted_terms.append(k_oil_deviation * 0.05)

        if weighted_terms:
            score = sum(weighted_terms)
        else:
            fallback = _safe_abs_mean((frame.get('k_oil', pd.Series(dtype='float64')) - 1.0).dropna())
            score = fallback if fallback is not None else float('nan')

        ranking_rows.append(
            {
                'scenario_key': scenario_key,
                'scenario_label': frame['scenario_label'].iloc[0] if 'scenario_label' in frame.columns else scenario_key,
                'avg_abs_mpfm_oil_density_error_pct': oil_density_error,
                'avg_abs_mpfm_oil_mass_error_pct': oil_mass_error,
                'avg_abs_separator_oil_density_error_pct': separator_density_error,
                'avg_abs_separator_oil_volume_error_pct': separator_volume_error,
                'avg_abs_separator_oil_error_pct': separator_oil_error,
                'avg_abs_k_oil_deviation_pct': k_oil_deviation,
                'score': score,
            }
        )

    ranking = pd.DataFrame(ranking_rows)
    if ranking.empty:
        return ranking
    return ranking.sort_values(by='score', ascending=True, na_position='last').reset_index(drop=True)


def _build_sidebar(catalog: dict, default_cases: pd.DataFrame):
    st.sidebar.title('Back-Flash')
    backend = detect_neqsim_backend()
    if backend.available:
        st.sidebar.success('NeqSim backend ativo.')
    else:
        st.sidebar.warning('NeqSim indisponivel. Rodando em modo shadow ate habilitar Java.')
        st.sidebar.caption(backend.detail)

    source_name = st.sidebar.radio(
        'Fonte dos dados do separador',
        options=['Casos internos do projeto', 'Upload CSV/Excel'],
    )

    if source_name == 'Casos internos do projeto':
        available_cases = default_cases[['case_label', 'case_id']].drop_duplicates()
        selected_labels = st.sidebar.multiselect(
            'Selecionar casos',
            options=available_cases['case_label'].tolist(),
            default=available_cases['case_label'].tolist()[:3],
        )
        if selected_labels:
            separator_df = default_cases[default_cases['case_label'].isin(selected_labels)].reset_index(drop=True)
        else:
            separator_df = default_cases.head(0).copy()
    else:
        uploaded_file = st.sidebar.file_uploader('Upload do Excel/CSV', type=['csv', 'xlsx', 'xlsm', 'xls'])
        if uploaded_file is None:
            separator_df = default_cases.head(0).copy()
        else:
            separator_df = load_separator_upload(uploaded_file)

    scenario_options = list(catalog.values())
    scenario = st.sidebar.selectbox(
        'Composicao',
        options=scenario_options,
        format_func=lambda item: item.label,
    )
    compare_gor_family = st.sidebar.toggle('Comparar GOR_337 / GOR_351 / GOR_393', value=False)
    sensitivity_options = []
    if compare_gor_family:
        default_keys = [key for key in ['GOR_337', 'GOR_351', 'GOR_393'] if key in catalog]
        sensitivity_options = st.sidebar.multiselect(
            'Cenarios de sensibilidade',
            options=list(catalog.keys()),
            default=default_keys,
            format_func=lambda key: catalog[key].label,
        )

    mpfm_pressure = st.sidebar.slider('Pressao MPFM (bara)', min_value=1.0, max_value=400.0, value=120.0, step=1.0)
    mpfm_temperature = st.sidebar.slider('Temperatura MPFM (C)', min_value=0.0, max_value=150.0, value=35.0, step=0.5)
    prefer_neqsim = st.sidebar.toggle('Tentar backend NeqSim quando disponivel', value=True)

    st.sidebar.divider()
    st.sidebar.caption(f'GOR selecionado: {_format_metric(scenario.estimated_gor_sm3_sm3)} Sm3/Sm3')
    st.sidebar.caption(f'MW mistura: {_format_metric(scenario.mixture_mw_g_mol)} g/mol')
    st.sidebar.caption(f'Fracao pesada: {_format_metric(scenario.heavy_fraction * 100.0, "%")}')
    if (
        'mpfm_pressure_bara' in separator_df.columns
        and separator_df['mpfm_pressure_bara'].notna().any()
    ) or (
        'mpfm_temperature_c' in separator_df.columns
        and separator_df['mpfm_temperature_c'].notna().any()
    ):
        st.sidebar.info('Upload contem P/T do MPFM por linha. Esses valores vao sobrescrever o slider quando presentes.')
    if (
        'separator_oil_volume_m3ph' in separator_df.columns
        and separator_df['separator_oil_volume_m3ph'].notna().any()
    ) or (
        'separator_oil_density_kgm3' in separator_df.columns
        and separator_df['separator_oil_density_kgm3'].notna().any()
    ):
        st.sidebar.info('Upload contem referencia de `CV` e/ou `Coriolis` do separador. O app vai comparar esses valores com o modelo.')
    return separator_df, scenario, sensitivity_options, mpfm_pressure, mpfm_temperature, prefer_neqsim


def _render_summary(results: pd.DataFrame, backend_mode: str) -> None:
    first = results.iloc[0] if not results.empty else None
    avg_k_oil = results['k_oil'].mean() if not results.empty else None
    avg_k_gas = results['k_gas'].mean() if not results.empty else None
    avg_fe = results['fe_20c_1atm'].mean() if 'fe_20c_1atm' in results.columns and not results.empty else None
    avg_rs = results['rs_20c_1atm_sm3_sm3'].mean() if 'rs_20c_1atm_sm3_sm3' in results.columns and not results.empty else None
    avg_dev = results[['deviation_k_oil_pct', 'deviation_k_gas_pct']].stack().mean() if not results.empty else None

    metric_1, metric_2, metric_3, metric_4, metric_5, metric_6 = st.columns(6)
    metric_1.metric('Modo de calculo', backend_mode.upper())
    metric_2.metric('K oil medio', _format_metric(avg_k_oil))
    metric_3.metric('K gas medio', _format_metric(avg_k_gas))
    metric_4.metric('Fe medio @20C/1atm', _format_metric(avg_fe))
    metric_5.metric('Rs medio @20C/1atm', _format_metric(avg_rs))
    metric_6.metric('Desvio medio vs FCS320', _format_metric(avg_dev, '%'))

    if first is not None:
        st.caption(
            f'Caso base: {first["case_label"]} | Cenario {first["scenario_key"]} | MPFM {first["mpfm_pressure_bara"]:.1f} bara / {first["mpfm_temperature_c"]:.1f} C | Ref. Fe/Rs: 20 C / 1 atm'
        )


def _render_user_guide() -> None:
    with st.expander('Passo a passo para o usuario', expanded=False):
        st.markdown(
            '### Funcionalidade 1 | Back-Flash de separador para MPFM subsea\n'
            '1. Selecione uma composicao aprovada do poco, de preferencia o `GOR_xxx` mais proximo do caso.\n'
            '2. Envie o Excel/CSV com `P/T` do separador, massa de oleo, massa de gas e, quando houver, `volume oleo CV` e `densidade Coriolis`.\n'
            '3. Informe `P/T` do MPFM pelos sliders ou deixe a planilha trazer `mpfm_pressure_bara` e `mpfm_temperature_c` por linha.\n'
            '4. Revise a tabela de `K`, densidades, `Fe`, `Rs` e os erros contra separador, MPFM e FCS320.\n'
            '5. Use o ranking de cenarios para escolher a composicao que melhor reconcilia `CV`, `Coriolis` e o MPFM.\n\n'
            '### Funcionalidade 2 | CPA Wet Gas + Tensao Superficial\n'
            '1. Objetivo: comparar `SRK-Peneloux` com `CPA` em casos com agua alta, MEG e quimicos.\n'
            '2. Entradas esperadas: composicao, agua, salinidade, WLR e `P/T` operacional.\n'
            '3. Saidas previstas: densidade da fase aquosa, tensao superficial e indicadores de wet gas.\n'
            '4. Status atual: planejada para a proxima entrega.\n\n'
            '### Funcionalidade 3 | LivePVT Virtual MPFM\n'
            '1. Objetivo: recalcular densidade de oleo, densidade de gas e GOR em tempo real para contingencia do FCS320.\n'
            '2. Entradas esperadas: vazoes do poco, gas lift, composicoes aprovadas e `P/T` do MPFM.\n'
            '3. Saidas previstas: `densidade oleo`, `densidade gas`, `GOR` e cenario sintetico de composicao.\n'
            '4. Status atual: planejada para a proxima entrega.\n\n'
            '### Funcionalidade 4 | Flow Assurance | Hidrato + WAT\n'
            '1. Objetivo: comparar o estado operacional do riser com a curva de hidrato e com o inicio de deposicao de cera.\n'
            '2. Entradas esperadas: composicao, `P/T` operacional, agua e perfil simplificado do riser.\n'
            '3. Saidas previstas: alerta de risco, curva de hidrato e janela de operacao segura.\n'
            '4. Status atual: planejada para a proxima entrega.'
        )


def _render_scenario_ranking(results: pd.DataFrame) -> None:
    if 'scenario_key' not in results.columns or results['scenario_key'].nunique() <= 1:
        return

    ranking = _build_scenario_ranking(results)
    if ranking.empty:
        return

    best = ranking.iloc[0]
    st.subheader('Ranking de cenarios')
    st.success(
        f'Melhor cenario atual: {best["scenario_key"]} | score {best["score"]:.2f}'
    )
    st.caption(
        'Menor score indica melhor reconciliacao do caso, priorizando erro de densidade e massa de oleo no MPFM.'
    )
    st.dataframe(
        ranking[
            [
                'scenario_key',
                'avg_abs_mpfm_oil_density_error_pct',
                'avg_abs_mpfm_oil_mass_error_pct',
                'avg_abs_separator_oil_density_error_pct',
                'avg_abs_separator_oil_volume_error_pct',
                'avg_abs_separator_oil_error_pct',
                'avg_abs_k_oil_deviation_pct',
                'score',
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_results_table(results: pd.DataFrame) -> None:
    show_columns = [
        'scenario_key',
        'case_label',
        'separator_pressure_bara',
        'separator_temperature_c',
        'mpfm_pressure_bara',
        'mpfm_temperature_c',
        'separator_oil_kgph',
        'separator_gas_kgph',
        'measured_separator_oil_volume_m3ph',
        'measured_separator_oil_density_kgm3',
        'measured_mpfm_oil_kgph',
        'measured_mpfm_gas_kgph',
        'measured_mpfm_water_kgph',
        'predicted_separator_oil_kgph',
        'predicted_separator_gas_kgph',
        'separator_oil_model_error_pct',
        'separator_gas_model_error_pct',
        'separator_oil_density_kgm3',
        'separator_oil_density_error_pct',
        'separator_oil_volume_error_pct',
        'backflash_oil_kgph',
        'backflash_gas_kgph',
        'k_oil',
        'k_gas',
        'model_k_oil',
        'model_k_gas',
        'backflash_gor_sm3_sm3',
        'predicted_separator_gor_sm3_sm3',
        'separator_oil_volume_derived_m3ph',
        'std_oil_volume_20c_1atm_m3ph',
        'std_gas_from_separator_oil_20c_1atm_sm3ph',
        'fe_20c_1atm',
        'rs_20c_1atm_sm3_sm3',
        'live_oil_density_kgm3',
        'live_gas_density_kgm3',
        'measured_mpfm_oil_density_kgm3',
        'measured_mpfm_gas_density_kgm3',
        'mpfm_oil_density_error_pct',
        'mpfm_gas_density_error_pct',
        'mpfm_oil_mass_error_pct',
        'mpfm_gas_mass_error_pct',
        'fcs320_k_oil',
        'fcs320_k_gas',
        'deviation_k_oil_pct',
        'deviation_k_gas_pct',
        'deviation_gor_pct',
    ]
    existing_columns = [column for column in show_columns if column in results.columns]
    st.dataframe(results[existing_columns], use_container_width=True, hide_index=True)


def _render_charts(results: pd.DataFrame) -> None:
    axis_label = 'case_label' if results['scenario_key'].nunique() == 1 else 'case_scenario_label'
    chart_data = results.copy()
    chart_data['case_scenario_label'] = chart_data['case_label'] + ' | ' + chart_data['scenario_key']
    chart_col_1, chart_col_2 = st.columns(2)

    with chart_col_1:
        k_chart = chart_data.melt(
            id_vars=[axis_label, 'scenario_key'],
            value_vars=['k_oil', 'k_gas'],
            var_name='series',
            value_name='value',
        )
        fig = px.bar(k_chart, x=axis_label, y='value', color='series', barmode='group', title='K-factors por caso')
        fig.update_layout(xaxis_title='', yaxis_title='K-factor')
        st.plotly_chart(fig, use_container_width=True)

    with chart_col_2:
        density_chart = chart_data.melt(
            id_vars=[axis_label, 'scenario_key'],
            value_vars=['live_oil_density_kgm3', 'live_gas_density_kgm3'],
            var_name='series',
            value_name='value',
        )
        fig = px.line(density_chart, x=axis_label, y='value', color='series', markers=True, title='Densidades LivePVT')
        fig.update_layout(xaxis_title='', yaxis_title='kg/m3')
        st.plotly_chart(fig, use_container_width=True)

    chart_col_3, chart_col_4 = st.columns(2)
    with chart_col_3:
        fig = px.line(
            chart_data,
            x=axis_label,
            y=['separator_gor_sm3_sm3', 'backflash_gor_sm3_sm3', 'fcs320_gor_sm3_sm3'],
            markers=True,
            title='GOR do separador vs back-flash',
        )
        fig.update_layout(xaxis_title='', yaxis_title='Sm3/Sm3')
        st.plotly_chart(fig, use_container_width=True)

    with chart_col_4:
        deviation_chart = chart_data.melt(
            id_vars=[axis_label, 'scenario_key'],
            value_vars=['deviation_k_oil_pct', 'deviation_k_gas_pct', 'deviation_gor_pct'],
            var_name='series',
            value_name='value',
        )
        fig = px.bar(deviation_chart, x=axis_label, y='value', color='series', barmode='group', title='Desvio vs FCS320')
        fig.update_layout(xaxis_title='', yaxis_title='%')
        st.plotly_chart(fig, use_container_width=True)

    chart_col_5, chart_col_6 = st.columns(2)
    with chart_col_5:
        fe_chart = chart_data.melt(
            id_vars=[axis_label, 'scenario_key'],
            value_vars=['fe_20c_1atm'],
            var_name='series',
            value_name='value',
        )
        fig = px.bar(fe_chart, x=axis_label, y='value', color='series', barmode='group', title='Fe @20C / 1 atm')
        fig.update_layout(xaxis_title='', yaxis_title='m3 std / m3 sep')
        st.plotly_chart(fig, use_container_width=True)

    with chart_col_6:
        rs_chart = chart_data.melt(
            id_vars=[axis_label, 'scenario_key'],
            value_vars=['rs_20c_1atm_sm3_sm3'],
            var_name='series',
            value_name='value',
        )
        fig = px.bar(rs_chart, x=axis_label, y='value', color='series', barmode='group', title='Rs @20C / 1 atm')
        fig.update_layout(xaxis_title='', yaxis_title='Sm3 / Sm3')
        st.plotly_chart(fig, use_container_width=True)

    has_separator_cv = 'measured_separator_oil_volume_m3ph' in chart_data.columns and chart_data['measured_separator_oil_volume_m3ph'].notna().any()
    has_separator_coriolis = 'measured_separator_oil_density_kgm3' in chart_data.columns and chart_data['measured_separator_oil_density_kgm3'].notna().any()
    if has_separator_cv or has_separator_coriolis:
        chart_col_7, chart_col_8 = st.columns(2)
        with chart_col_7:
            if has_separator_cv:
                fig = px.bar(
                    chart_data,
                    x=axis_label,
                    y=['measured_separator_oil_volume_m3ph', 'separator_oil_volume_derived_m3ph'],
                    barmode='group',
                    title='Separador | volume de oleo CV vs modelo',
                )
                fig.update_layout(xaxis_title='', yaxis_title='m3')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info('Sem volume de oleo do separador no arquivo para comparar com o modelo.')

        with chart_col_8:
            if has_separator_coriolis:
                fig = px.bar(
                    chart_data,
                    x=axis_label,
                    y=['measured_separator_oil_density_kgm3', 'separator_oil_density_kgm3'],
                    barmode='group',
                    title='Separador | densidade Coriolis vs modelo',
                )
                fig.update_layout(xaxis_title='', yaxis_title='kg/m3')
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info('Sem densidade Coriolis do separador no arquivo para comparar com o modelo.')


def main() -> None:
    st.title('SIMULPVT | Back-Flash Dashboard')
    st.write(
        'Entrega focada em auditoria termodinamica de back-flash para casos de separador, '
        'usando `NeqSim` real quando disponivel e com comparacao direta contra MPFM, `CV` e `Coriolis`.'
    )
    _render_user_guide()

    catalog = get_catalog()
    default_cases = get_default_cases()
    separator_df, scenario, sensitivity_options, mpfm_pressure, mpfm_temperature, prefer_neqsim = _build_sidebar(catalog, default_cases)

    if separator_df.empty:
        st.info('Selecione ao menos um caso interno ou envie um arquivo CSV/Excel para continuar.')
        return

    selected_scenarios = [scenario]
    if sensitivity_options:
        selected_scenarios = [catalog[key] for key in sensitivity_options]

    result_frames = []
    backend = None
    for active_scenario in selected_scenarios:
        scenario_results, backend = calculate_backflash_table(
            separator_df=separator_df,
            scenario=active_scenario,
            mpfm_pressure_bara=mpfm_pressure,
            mpfm_temperature_c=mpfm_temperature,
            prefer_neqsim=prefer_neqsim,
        )
        result_frames.append(scenario_results)
    results = pd.concat(result_frames, ignore_index=True)

    _render_summary(results, backend.mode)
    _render_scenario_ranking(results)

    st.subheader('Tabela de resultados')
    _render_results_table(results)

    st.subheader('Graficos')
    _render_charts(results)

    st.subheader('Download')
    st.download_button(
        label='Baixar resultados em CSV',
        data=results.to_csv(index=False).encode('utf-8'),
        file_name='backflash_results.csv',
        mime='text/csv',
    )

    st.subheader('Notas da versao')
    st.markdown(
        '- `neqsim`: executa duas flashes reais, uma no separador e outra no MPFM, e escala as fracoes de fase para as massas medidas.\n'
        '- `Fe` e `Rs`: agora saem da fase oleo do separador levada para `20 C / 1 atm`, usando flash termodinamico real do NeqSim.\n'
        '- `shadow`: continua disponivel como contingencia se o backend real falhar.\n'
        '- Estrutura pronta para receber os proximos modulos: CPA Wet Gas, LivePVT e Flow Assurance.'
    )


if __name__ == '__main__':
    main()
