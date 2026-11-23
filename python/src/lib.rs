use calculus::gex::{StrikeExposure, rank_strikes};
use calculus::indicators::{GrowthCadence, GrowthObservation, IndicatorState, MarginMomentum};
use calculus::options::{
    IdentifiedContract, MaxPain, OptionContract, OptionKind, OptionSnapshot, OptionsError,
    Valuation, aggregate, max_pain,
};
use market_data::Source;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::path::PathBuf;

type Contract = (String, String, f64, i64, f64, f64, f64);
type Strike = (f64, f64, f64);

fn invalid(error: OptionsError) -> PyErr {
    PyValueError::new_err(format!("Invalid options input: {error:?}"))
}

fn snapshot(
    observed_at: i64,
    available_at: i64,
    valued_at: i64,
    spot: f64,
    contracts: Vec<Contract>,
) -> PyResult<OptionSnapshot> {
    if contracts.len() > 10_000 {
        return Err(PyValueError::new_err("Too many option contracts"));
    }
    let contracts = contracts
        .into_iter()
        .map(|(id, kind, strike, expiry, iv, interest, multiplier)| {
            let kind = match kind.as_str() {
                "call" => OptionKind::Call,
                "put" => OptionKind::Put,
                _ => return Err(PyValueError::new_err("Invalid option kind")),
            };
            let contract = OptionContract::new(kind, strike, expiry, iv, interest, multiplier)
                .map_err(invalid)?;
            IdentifiedContract::new(id, contract).map_err(invalid)
        })
        .collect::<PyResult<Vec<_>>>()?;
    let valuation = Valuation::new(spot, valued_at).map_err(invalid)?;
    OptionSnapshot::new(observed_at, available_at, valuation, contracts).map_err(invalid)
}

#[pyfunction]
fn strike_exposures(
    observed_at: i64,
    available_at: i64,
    valued_at: i64,
    spot: f64,
    contracts: Vec<Contract>,
) -> PyResult<Vec<Strike>> {
    let snapshot = snapshot(observed_at, available_at, valued_at, spot, contracts)?;
    let summary = aggregate(&snapshot).map_err(invalid)?;
    Ok(summary
        .strikes
        .into_iter()
        .map(|level| (level.strike, level.call, level.put))
        .collect())
}

#[pyfunction]
fn ranked_walls(
    levels: Vec<Strike>,
    spot: f64,
    distance: Option<f64>,
) -> PyResult<(Vec<Strike>, Vec<Strike>)> {
    let levels: Vec<_> = levels
        .into_iter()
        .map(|(strike, call, put)| StrikeExposure { strike, call, put })
        .collect();
    if levels.iter().any(|level| {
        !level.strike.is_finite()
            || level.strike <= 0.0
            || !level.call.is_finite()
            || level.call < 0.0
            || !level.put.is_finite()
            || level.put > 0.0
    }) {
        return Err(invalid(OptionsError::InvalidInput));
    }
    let ranks = rank_strikes(&levels, spot, distance).map_err(invalid)?;
    let tuples = |levels: Vec<StrikeExposure>| {
        levels
            .into_iter()
            .map(|level| (level.strike, level.call, level.put))
            .collect()
    };
    Ok((tuples(ranks.calls), tuples(ranks.puts)))
}

#[pyfunction]
fn options_max_pain(contracts: Vec<Contract>) -> PyResult<Option<f64>> {
    let snapshot = snapshot(0, 0, 0, 1.0, contracts)?;
    match max_pain(&snapshot).map_err(invalid)? {
        MaxPain::Strike(strike) => Ok(Some(strike)),
        MaxPain::Empty | MaxPain::MixedExpiry | MaxPain::ZeroOpenInterest => Ok(None),
    }
}

fn invalid_market(_: market_data::InvalidData) -> PyErr {
    PyValueError::new_err("Invalid public market data")
}

#[pyfunction]
fn market_request(
    source: &str,
    asset: &str,
) -> PyResult<(&'static str, Vec<(&'static str, String)>)> {
    let source = match source {
        "24h" => Source::BitgetHourlyGrowth,
        "30d" => Source::BitgetDailyGrowth,
        "rate" => Source::BitgetLoanRate,
        _ => {
            return Err(PyValueError::new_err(
                "Unsupported public market data source",
            ));
        }
    };
    let request = market_data::request(source, asset).map_err(invalid_market)?;
    Ok((request.url, request.parameters))
}

#[pyfunction]
fn bitget_growth(payload: &str, received_ms: i64) -> PyResult<Vec<(i64, f64)>> {
    market_data::growth(payload, received_ms).map_err(invalid_market)
}

#[pyfunction]
fn bitget_rate(payload: &str) -> PyResult<(i64, f64, f64)> {
    let rate = market_data::loan_rate(payload).map_err(invalid_market)?;
    Ok((rate.observed_ms, rate.daily, rate.annual))
}

fn invalid_margin(err: calculus::indicators::IndicatorError) -> PyErr {
    PyValueError::new_err(format!("Invalid margin observation: {err}"))
}

#[pyfunction]
fn margin_momentum(period: &str, points: Vec<(i64, f64)>) -> PyResult<Vec<Option<f64>>> {
    let cadence = match period {
        "24h" => GrowthCadence::Hourly,
        "30d" => GrowthCadence::Daily,
        _ => return Err(PyValueError::new_err("Unsupported Bitget period")),
    };
    let mut momentum = MarginMomentum::with_millisecond_cadence(cadence);
    points
        .into_iter()
        .map(|(timestamp_ms, growth)| {
            let point = GrowthObservation::new(timestamp_ms, timestamp_ms, growth)
                .map_err(invalid_margin)?;
            let state = momentum.update(point).map_err(|err| {
                PyValueError::new_err(format!("Invalid margin observation: {err}"))
            })?;
            Ok(match state {
                IndicatorState::Ready { value, .. } => Some(value),
                IndicatorState::WarmingUp { .. } | IndicatorState::Gap { .. } => None,
            })
        })
        .collect()
}

#[pyfunction]
fn archive_index(path: PathBuf) -> PyResult<Vec<(String, String, String)>> {
    use archive::local_archive::{ArchiveError, index};

    Ok(index(&path)
        .map_err(|err| match err {
            ArchiveError::Database => PyValueError::new_err("Cannot read local archive database"),
            ArchiveError::Invalid => PyValueError::new_err(
                "No complete successful BTC options chains or invalid archive metadata",
            ),
        })?
        .into_iter()
        .map(|collection| {
            (
                collection.id,
                collection.first_available_at,
                collection.available_at,
            )
        })
        .collect())
}

#[pymodule]
fn koopec_calculus(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(strike_exposures, module)?)?;
    module.add_function(wrap_pyfunction!(options_max_pain, module)?)?;
    module.add_function(wrap_pyfunction!(ranked_walls, module)?)?;
    module.add_function(wrap_pyfunction!(market_request, module)?)?;
    module.add_function(wrap_pyfunction!(bitget_growth, module)?)?;
    module.add_function(wrap_pyfunction!(bitget_rate, module)?)?;
    module.add_function(wrap_pyfunction!(archive_index, module)?)?;
    module.add_function(wrap_pyfunction!(margin_momentum, module)?)
}
