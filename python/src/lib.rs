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
    let valuation = Valuation::new(spot, valued_at).map_err(invalid)?;
    OptionSnapshot::new(
        observed_at,
        available_at,
        valuation,
        identified_contracts(contracts)?,
    )
    .map_err(invalid)
}

fn identified_contracts(contracts: Vec<Contract>) -> PyResult<Vec<IdentifiedContract>> {
    if contracts.len() > 10_000 {
        return Err(PyValueError::new_err("Too many option contracts"));
    }
    contracts
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
        .collect()
}

#[pyfunction]
fn gamma_grid(
    py: Python<'_>,
    valuation: (f64, i64),
    contracts: Vec<Contract>,
    prices: Vec<f64>,
    find_flips: bool,
) -> PyResult<Vec<f64>> {
    let (spot, time) = valuation;
    let valuation = Valuation::with_microseconds(spot, time).map_err(invalid)?;
    if contracts
        .iter()
        .any(|contract| !contract.4.is_finite() || contract.4 <= 0.0)
    {
        return Err(PyValueError::new_err(
            "Volatility is outside the supported numeric range.",
        ));
    }
    let contracts = identified_contracts(contracts)
        .map_err(|error| PyValueError::new_err(format!("Exposure inputs are invalid: {error}")))?;
    let snapshot = OptionSnapshot::new(time, time, valuation, contracts).map_err(invalid)?;
    py.detach(|| {
        if find_flips {
            calculus::gex::grid_flips(&snapshot, &prices)
        } else {
            calculus::gex::grid_exposures(&snapshot, &prices)
        }
    })
    .map_err(|error| PyValueError::new_err(format!("Exposure calculation failed: {error:?}")))
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
        "book" => Source::BybitBook,
        "get_instruments" => Source::DeribitInstruments,
        "get_book_summary_by_currency" => Source::DeribitSummary,
        "get_index_price" => Source::DeribitIndex,
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

#[pyfunction(signature = (path, asset=None))]
fn archive_index(path: PathBuf, asset: Option<&str>) -> PyResult<Vec<(String, String, String)>> {
    use archive::local_archive::{ArchiveError, index, market_index};

    let collections = match asset {
        Some(asset) => market_index(&path, asset),
        None => index(&path),
    };
    Ok(collections
        .map_err(|err| match err {
            ArchiveError::Database => PyValueError::new_err("Cannot read local archive database"),
            ArchiveError::Invalid => PyValueError::new_err(
                "No complete successful BTC options chains or invalid archive metadata",
            ),
            error @ (ArchiveError::Changed | ArchiveError::Metadata(_)) => {
                archive_read_error(error, "read the local archive index")
            }
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

fn deribit_json(text: &str) -> PyResult<serde_json::Value> {
    serde_json::from_str(text)
        .map_err(|error| PyValueError::new_err(format!("Invalid Deribit JSON: {error}")))
}

#[pyfunction]
fn deribit_spot(payload: &str) -> PyResult<f64> {
    market_data::deribit::spot(&deribit_json(payload)?)
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

#[pyfunction]
fn deribit_chain(instruments: &str, quotes: &str, asset: &str) -> PyResult<Vec<Contract>> {
    let chain = market_data::deribit::normalize_chain(
        &deribit_json(instruments)?,
        &deribit_json(quotes)?,
        asset,
    )
    .map_err(|error| PyValueError::new_err(error.to_string()))?;
    Ok(chain.into_iter().map(deribit_contract_row).collect())
}

type SavedOptionsRow = (String, String, String, String, String, Option<String>);
type MarketRow = (String, String, String, String, String, String, String);
type MarketRows = Vec<(String, String, String, String, String)>;

fn storage_error(py: Python<'_>, error: archive::storage::StorageError) -> PyErr {
    let message = error.to_string();
    if let Some(class) = error.sqlite_exception() {
        return match py
            .import("sqlite3")
            .and_then(|module| module.getattr(class))
            .and_then(|class| class.call1((message,)))
        {
            Ok(instance) => PyErr::from_value(instance),
            Err(error) => error,
        };
    }
    match error {
        archive::storage::StorageError::Io(_) => pyo3::exceptions::PyOSError::new_err(message),
        _ => PyValueError::new_err(message),
    }
}

#[pyfunction]
fn save_options(py: Python<'_>, path: PathBuf, row: SavedOptionsRow) -> PyResult<()> {
    let (available_at, asset, observed_at, source, content, depth) = row;
    let snapshot = archive::storage::SavedOptions {
        available_at,
        asset,
        observed_at,
        source,
        content,
        depth,
    };
    py.detach(|| archive::storage::save_options(&path, &snapshot))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn load_options(py: Python<'_>, path: PathBuf) -> PyResult<Vec<(String, Option<String>)>> {
    py.detach(|| archive::storage::load_options(&path))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn save_market(
    py: Python<'_>,
    path: PathBuf,
    row: MarketRow,
    collection_start: Option<String>,
    compact: bool,
) -> PyResult<()> {
    let (asset, source, requested, available, payload, collection, error) = row;
    let observation = archive::storage::Observation {
        asset,
        source,
        requested,
        available,
        payload,
        collection,
        error,
    };
    py.detach(|| {
        archive::storage::save_market(&path, &observation, collection_start.as_deref(), compact)
    })
    .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn load_market(
    py: Python<'_>,
    path: PathBuf,
    bounds: (String, String, String),
    sources: Vec<String>,
) -> PyResult<MarketRows> {
    let (asset, start, end) = bounds;
    let window = archive::storage::MarketWindow {
        asset,
        start,
        end,
        sources,
    };
    let observations = py
        .detach(|| archive::storage::load_market(&path, window))
        .map_err(|error| storage_error(py, error))?;
    Ok(observations
        .into_iter()
        .map(|row| {
            (
                row.source,
                row.requested,
                row.available,
                row.payload,
                row.collection,
            )
        })
        .collect())
}

type CandleKey = (String, String, String);
type CandleRow = (i64, f64, f64, f64, f64, f64, f64, i64);

fn candle_market((exchange, symbol, interval): CandleKey) -> archive::storage::candles::Market {
    archive::storage::candles::Market {
        exchange,
        symbol,
        interval,
    }
}

#[pyfunction]
fn initialize_candles(py: Python<'_>, path: PathBuf) -> PyResult<()> {
    py.detach(|| archive::storage::candles::initialize(&path))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn upsert_candles(
    py: Python<'_>,
    path: PathBuf,
    market: CandleKey,
    rows: Vec<CandleRow>,
) -> PyResult<()> {
    let market = candle_market(market);
    let candles: Vec<_> = rows
        .into_iter()
        .map(
            |(open_time_ms, open, high, low, close, volume, quote_volume, trades)| {
                archive::storage::candles::Candle {
                    open_time_ms,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume,
                    trades,
                }
            },
        )
        .collect();
    py.detach(|| archive::storage::candles::upsert(&path, &market, &candles))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn mark_candle_download(
    py: Python<'_>,
    path: PathBuf,
    market: CandleKey,
    bounds: (i64, i64),
) -> PyResult<()> {
    let market = candle_market(market);
    py.detach(|| archive::storage::candles::mark_downloaded(&path, &market, bounds))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn missing_candle_ranges(
    py: Python<'_>,
    path: PathBuf,
    market: CandleKey,
    bounds: (i64, i64),
) -> PyResult<Vec<(i64, i64)>> {
    let market = candle_market(market);
    py.detach(|| archive::storage::candles::missing_ranges(&path, &market, bounds))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn load_candles(
    py: Python<'_>,
    path: PathBuf,
    market: CandleKey,
    bounds: (i64, i64),
) -> PyResult<Vec<CandleRow>> {
    let market = candle_market(market);
    let candles = py
        .detach(|| archive::storage::candles::load(&path, &market, bounds))
        .map_err(|error| storage_error(py, error))?;
    Ok(candles
        .into_iter()
        .map(|row| {
            (
                row.open_time_ms,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.quote_volume,
                row.trades,
            )
        })
        .collect())
}

#[pyfunction]
fn bybit_interest_page(payload: &str) -> PyResult<(Vec<(i64, f64)>, String)> {
    let page = market_data::bybit::interest_page(payload).map_err(PyValueError::new_err)?;
    Ok((page.samples, page.cursor))
}

#[pyfunction]
fn oi_momentum(
    interval_seconds: i64,
    samples: Vec<(i64, i64, f64, f64)>,
) -> PyResult<Vec<Option<f64>>> {
    use calculus::indicators::{IndicatorError, InterestObservation, Interval, OiMomentum};
    let interval = match interval_seconds {
        300 => Interval::FiveMinutes,
        3_600 => Interval::Hourly,
        _ => return Err(PyValueError::new_err("Invalid open-interest interval")),
    };
    let mut indicator = OiMomentum::with_microseconds(interval);
    samples
        .into_iter()
        .map(|(observed, received, oi, price)| {
            let point =
                InterestObservation::new(observed, received, oi, price).map_err(invalid_margin)?;
            match indicator.update(point) {
                Ok(IndicatorState::Ready { value, .. }) => Ok(Some(value)),
                Ok(IndicatorState::WarmingUp { .. } | IndicatorState::Gap { .. }) => Ok(None),
                Err(IndicatorError::OutOfOrder) => Err(PyValueError::new_err(
                    "Market observations must be strictly chronological",
                )),
                Err(IndicatorError::Arithmetic) => {
                    Err(PyValueError::new_err("OI percentage change overflow"))
                }
                Err(error) => Err(invalid_margin(error)),
            }
        })
        .collect()
}

#[pyfunction]
fn daily_receipts(receipts: Vec<(usize, i64)>) -> Vec<usize> {
    calculus::options::select_daily_receipts(receipts.into_iter())
}

#[pyfunction]
fn replay_plan_indices(windows: Vec<(i64, i64)>, quotes: Vec<i64>) -> PyResult<Vec<Option<usize>>> {
    let plans: Vec<_> = windows
        .into_iter()
        .map(|(available, expires)| calculus::plans::PlanWindow { available, expires })
        .collect();
    calculus::plans::active_plan_indices(&plans, &quotes)
        .map_err(|_| PyValueError::new_err("Replay plans must have ordered, valid receipt windows"))
}

#[pyfunction]
fn validate_archive(py: Python<'_>, path: PathBuf) -> PyResult<()> {
    py.detach(|| archive::storage::backup::validate(&path))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn backup_archive(py: Python<'_>, source: PathBuf, destination: PathBuf) -> PyResult<()> {
    py.detach(|| archive::storage::backup::snapshot(&source, &destination))
        .map_err(|error| storage_error(py, error))
}

type MergeTimelines = Vec<(String, String, String, String, usize, usize)>;
type DepthSide = Vec<(f64, f64)>;

#[pyfunction(signature = (source, destination=None))]
fn merge_archive(
    py: Python<'_>,
    source: PathBuf,
    destination: Option<PathBuf>,
) -> PyResult<(usize, usize, MergeTimelines)> {
    let report = py
        .detach(|| match destination {
            Some(destination) => archive::storage::merge::merge(&source, &destination),
            None => archive::storage::merge::check(&source),
        })
        .map_err(|error| storage_error(py, error))?;
    Ok((
        report.observations,
        report.duplicates,
        report
            .timelines
            .into_iter()
            .map(|row| {
                (
                    row.asset,
                    row.source.to_owned(),
                    row.first,
                    row.last,
                    row.successful,
                    row.missing,
                )
            })
            .collect(),
    ))
}

#[pyfunction]
fn depth_time(payload: &str, asset: &str) -> PyResult<i64> {
    market_data::depth_time(payload, asset).map_err(|_| {
        PyValueError::new_err("Bybit depth request failed or returned an invalid timestamp")
    })
}

#[pyfunction]
fn parse_depth(
    payload: &str,
    asset: &str,
    received_us: i64,
) -> PyResult<(i64, DepthSide, DepthSide)> {
    let book = market_data::depth(payload, asset, received_us).map_err(|_| {
        PyValueError::new_err(
            "Bybit depth request failed or returned invalid depth or availability",
        )
    })?;
    let levels = |levels: Vec<calculus::indicators::BookLevel>| {
        levels
            .into_iter()
            .map(|level| (level.price(), level.quantity()))
            .collect()
    };
    Ok((book.observed_ms, levels(book.bids), levels(book.asks)))
}

#[pyfunction]
fn depth_notional_rate(bids: DepthSide, asks: DepthSide) -> PyResult<f64> {
    let levels = |rows: DepthSide| {
        rows.into_iter()
            .map(|(price, quantity)| calculus::indicators::BookLevel::new(price, quantity))
            .collect::<Result<Vec<_>, _>>()
    };
    levels(bids)
        .and_then(|bids| {
            levels(asks).and_then(|asks| calculus::indicators::book_rate(&bids, &asks))
        })
        .ok()
        .flatten()
        .ok_or_else(|| {
            PyValueError::new_err("Recorded order-book notional must be finite and positive")
        })
}

#[pyfunction]
fn tunnel_state(lower: f64, upper: f64, flip: f64, tight_width: f64, forced: Option<u8>) -> u8 {
    use calculus::plans::{PositiveTunnel, TunnelState};
    let Ok(tunnel) = PositiveTunnel::new(lower, upper, flip) else {
        return 0;
    };
    if let Some(state) = forced {
        return state;
    }
    match tunnel.classify(tight_width) {
        Ok(TunnelState::Tight) => 1,
        Ok(TunnelState::FlipInside) => 2,
        Ok(TunnelState::FlipBelow) => 3,
        Err(_) => 0,
    }
}

#[pyfunction]
fn tunnel_direction(bounds: (f64, f64, f64), state: u8, price: f64, proximity: f64) -> i8 {
    use calculus::plans::{PositiveTunnel, TunnelState};
    let state = match state {
        1 => TunnelState::Tight,
        2 => TunnelState::FlipInside,
        3 => TunnelState::FlipBelow,
        _ => return 0,
    };
    PositiveTunnel::new(bounds.0, bounds.1, bounds.2)
        .map_or(0, |tunnel| tunnel.direction(state, price, proximity))
}

#[pyfunction]
fn tunnel_entry_allowed(
    direction: i8,
    counts: (usize, usize, usize),
    oi_required: bool,
    oi_direction: i8,
) -> bool {
    use calculus::{
        accounts::Side,
        strategy::{EntryGate, GateResult},
    };
    let side = |direction| match direction {
        1 => Some(Side::Long),
        -1 => Some(Side::Short),
        _ => None,
    };
    let Some(direction) = side(direction) else {
        return false;
    };
    let (required, agreeing, available) = counts;
    let gate = EntryGate {
        required,
        agreeing,
        enabled_sources: available,
        gex_enabled: oi_required,
        oi_enabled: oi_required,
        fresh_oi_side: side(oi_direction),
    };
    gate.evaluate(direction) == GateResult::Allowed
}

#[pyfunction]
fn market_due(
    py: Python<'_>,
    path: PathBuf,
    key: (String, String),
    now: String,
    interval: i64,
) -> PyResult<bool> {
    py.detach(|| archive::storage::market_due(&path, &key.0, &key.1, &now, interval))
        .map_err(|error| storage_error(py, error))
}

#[pyfunction]
fn prune_unmanaged_archive(py: Python<'_>, path: PathBuf, cutoff: String) -> PyResult<bool> {
    py.detach(|| archive::storage::prune_unmanaged(&path, &cutoff))
        .map_err(|error| storage_error(py, error))
}

type TunnelBarRow = (i64, (f64, f64, f64, f64), i8, Option<f64>, bool);
type TunnelRiskRow = (f64, f64, f64, f64, f64, f64, bool);
type TunnelTradeRow = (
    f64,
    &'static str,
    usize,
    usize,
    f64,
    f64,
    f64,
    f64,
    f64,
    &'static str,
);
type TunnelResult = (Vec<(f64, f64)>, Vec<TunnelTradeRow>);

#[pyfunction]
fn simulate_snapshot_tunnel(
    py: Python<'_>,
    rows: Vec<TunnelBarRow>,
    capital: f64,
    risk: TunnelRiskRow,
) -> PyResult<TunnelResult> {
    use calculus::{
        accounts::Side,
        execution::{TunnelBar, TunnelRisk, simulate_tunnel},
    };
    let (
        fee_pct,
        stop_loss_pct,
        take_profit_pct,
        minimum_order,
        slippage_bps,
        funding_pct,
        allow_reentry,
    ) = risk;
    let risk = TunnelRisk {
        fee_pct,
        stop_loss_pct,
        take_profit_pct,
        minimum_order,
        slippage_bps,
        funding_pct,
        allow_reentry,
    };
    let bars: Vec<_> = rows
        .into_iter()
        .map(
            |(time_us, (open, high, low, close), direction, target_ceiling, ends_session)| {
                TunnelBar {
                    time_us,
                    open,
                    high,
                    low,
                    close,
                    target_ceiling,
                    ends_session,
                    entry: match direction {
                        1 => Some(Side::Long),
                        -1 => Some(Side::Short),
                        _ => None,
                    },
                }
            },
        )
        .collect();
    let run = py
        .detach(|| simulate_tunnel(&bars, capital, &risk))
        .map_err(|err| PyValueError::new_err(format!("Snapshot tunnel execution failed: {err}")))?;
    Ok((
        run.marks
            .into_iter()
            .map(|mark| (mark.equity, mark.quantity))
            .collect(),
        run.trades
            .into_iter()
            .map(|trade| {
                (
                    trade.capital,
                    match trade.side {
                        Side::Long => "Long",
                        Side::Short => "Short",
                    },
                    trade.entry,
                    trade.exit,
                    trade.entry_price,
                    trade.exit_price,
                    trade.quantity,
                    trade.pnl,
                    trade.return_pct,
                    trade.reason,
                )
            })
            .collect(),
    ))
}

fn deribit_contract_row(contract: market_data::deribit::Contract) -> Contract {
    (
        contract.instrument,
        contract.side.as_str().to_owned(),
        contract.strike,
        contract.expiry_ms,
        contract.iv,
        contract.open_interest,
        contract.multiplier,
    )
}

type ArchiveSnapshotRow = (i64, f64, Vec<Contract>);

#[pyfunction]
fn archive_replay_snapshots(
    py: Python<'_>,
    path: PathBuf,
    version: (i128, u64),
    cutoff_us: Option<i64>,
) -> PyResult<Vec<ArchiveSnapshotRow>> {
    use archive::local_archive::{ArchiveVersion, ReplaySelection, replay_snapshots};
    let (modified_ns, size) = version;
    let selection = cutoff_us.map_or(ReplaySelection::Daily, ReplaySelection::Through);
    py.detach(|| replay_snapshots(&path, ArchiveVersion { modified_ns, size }, selection))
        .map_err(|error| archive_read_error(error, "load archived replay snapshots"))
        .map(|snapshots| {
            snapshots
                .into_iter()
                .map(|snapshot| {
                    (
                        snapshot.receipt_us,
                        snapshot.spot,
                        snapshot
                            .contracts
                            .into_iter()
                            .map(deribit_contract_row)
                            .collect(),
                    )
                })
                .collect()
        })
}

fn archive_read_error(error: archive::local_archive::ArchiveError, operation: &str) -> PyErr {
    use archive::local_archive::ArchiveError;
    match error {
        ArchiveError::Changed => PyValueError::new_err(
            "Local archive changed while loading; refresh to load its new window.",
        ),
        ArchiveError::Metadata(error) => PyErr::from(error),
        error => PyValueError::new_err(format!("Cannot {operation}: {error:?}")),
    }
}

type ArchiveGexRow = (i64, f64, f64, f64, f64, f64, f64, f64, f64, f64, f64);

#[pyfunction]
#[pyo3(signature = (path, distance, *, version=None))]
fn archive_gex_history(
    py: Python<'_>,
    path: PathBuf,
    distance: Option<f64>,
    version: Option<(i128, u64)>,
) -> PyResult<Vec<ArchiveGexRow>> {
    use archive::local_archive::{ArchiveVersion, gex_history, gex_history_for_version};
    let history = py
        .detach(|| match version {
            Some((modified_ns, size)) => {
                gex_history_for_version(&path, distance, ArchiveVersion { modified_ns, size })
            }
            None => gex_history(&path, distance),
        })
        .map_err(|error| archive_read_error(error, "calculate archived GEX history"))?;
    let price = |value: Option<f64>| value.unwrap_or(f64::NAN);
    Ok(history
        .into_iter()
        .map(|row| {
            (
                row.receipt_us,
                row.spot,
                row.net,
                row.call,
                row.put,
                row.absolute,
                price(row.flip),
                price(row.calls[0]),
                price(row.calls[1]),
                price(row.puts[0]),
                price(row.puts[1]),
            )
        })
        .collect())
}

#[pymodule]
fn koopec_calculus(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(archive_gex_history, module)?)?;
    module.add_function(wrap_pyfunction!(archive_replay_snapshots, module)?)?;
    module.add_function(wrap_pyfunction!(gamma_grid, module)?)?;
    module.add_function(wrap_pyfunction!(simulate_snapshot_tunnel, module)?)?;
    module.add_function(wrap_pyfunction!(market_due, module)?)?;
    module.add_function(wrap_pyfunction!(prune_unmanaged_archive, module)?)?;
    module.add_function(wrap_pyfunction!(tunnel_entry_allowed, module)?)?;
    module.add_function(wrap_pyfunction!(merge_archive, module)?)?;
    module.add_function(wrap_pyfunction!(depth_time, module)?)?;
    module.add_function(wrap_pyfunction!(parse_depth, module)?)?;
    module.add_function(wrap_pyfunction!(depth_notional_rate, module)?)?;
    module.add_function(wrap_pyfunction!(tunnel_state, module)?)?;
    module.add_function(wrap_pyfunction!(tunnel_direction, module)?)?;
    module.add_function(wrap_pyfunction!(bybit_interest_page, module)?)?;
    module.add_function(wrap_pyfunction!(oi_momentum, module)?)?;
    module.add_function(wrap_pyfunction!(daily_receipts, module)?)?;
    module.add_function(wrap_pyfunction!(replay_plan_indices, module)?)?;
    module.add_function(wrap_pyfunction!(validate_archive, module)?)?;
    module.add_function(wrap_pyfunction!(backup_archive, module)?)?;
    module.add_function(wrap_pyfunction!(strike_exposures, module)?)?;
    module.add_function(wrap_pyfunction!(options_max_pain, module)?)?;
    module.add_function(wrap_pyfunction!(ranked_walls, module)?)?;
    module.add_function(wrap_pyfunction!(market_request, module)?)?;
    module.add_function(wrap_pyfunction!(bitget_growth, module)?)?;
    module.add_function(wrap_pyfunction!(bitget_rate, module)?)?;
    module.add_function(wrap_pyfunction!(archive_index, module)?)?;
    module.add_function(wrap_pyfunction!(deribit_chain, module)?)?;
    module.add_function(wrap_pyfunction!(deribit_spot, module)?)?;
    module.add_function(wrap_pyfunction!(save_options, module)?)?;
    module.add_function(wrap_pyfunction!(load_options, module)?)?;
    module.add_function(wrap_pyfunction!(save_market, module)?)?;
    module.add_function(wrap_pyfunction!(load_market, module)?)?;
    module.add_function(wrap_pyfunction!(initialize_candles, module)?)?;
    module.add_function(wrap_pyfunction!(upsert_candles, module)?)?;
    module.add_function(wrap_pyfunction!(mark_candle_download, module)?)?;
    module.add_function(wrap_pyfunction!(missing_candle_ranges, module)?)?;
    module.add_function(wrap_pyfunction!(load_candles, module)?)?;
    module.add_function(wrap_pyfunction!(margin_momentum, module)?)
}
