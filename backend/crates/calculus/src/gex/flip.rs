use super::aggregate;
use crate::options::{OptionSnapshot, OptionsError, Valuation};

/// Immutable bounded grid and bisection settings.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FlipSearchConfig {
    lower: f64,
    upper: f64,
    intervals: usize,
    tolerance: f64,
    iterations: usize,
}
impl FlipSearchConfig {
    /// Construct a bounded search. The interval count is limited to 10,000.
    pub fn new(
        lower: f64,
        upper: f64,
        intervals: usize,
        tolerance: f64,
        iterations: usize,
    ) -> Result<Self, OptionsError> {
        if !lower.is_finite()
            || !upper.is_finite()
            || lower <= 0.0
            || upper <= lower
            || !(2..=10_000).contains(&intervals)
            || !tolerance.is_finite()
            || tolerance <= 0.0
            || iterations == 0
        {
            return Err(OptionsError::InvalidInput);
        }
        Ok(Self {
            lower,
            upper,
            intervals,
            tolerance,
            iterations,
        })
    }
}
/// Search outcome. Flat or zero-only profiles do not establish a crossing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FlipStatus {
    Found,
    NoCrossing,
    ZeroPlateau,
    InsufficientResolution,
    Nonconverged,
}
/// Roots, explicit configuration and result status.
#[derive(Debug, Clone, PartialEq)]
pub struct FlipResult {
    pub config: FlipSearchConfig,
    pub status: FlipStatus,
    pub roots: Vec<f64>,
    pub spot: f64,
}
impl FlipResult {
    /// Closest root to spot, choosing the lower root on ties.
    pub fn nearest(&self) -> Option<f64> {
        self.roots.iter().copied().min_by(|a, b| {
            (a - self.spot)
                .abs()
                .total_cmp(&(b - self.spot).abs())
                .then(a.total_cmp(b))
        })
    }
}
fn value(snapshot: &OptionSnapshot, spot: f64) -> Result<f64, OptionsError> {
    let mut copy = snapshot.clone();
    copy.valuation = Valuation::new(spot, snapshot.valuation.time)?;
    Ok(aggregate(&copy)?.totals.signed)
}
fn refine(
    snapshot: &OptionSnapshot,
    mut left: f64,
    mut right: f64,
    mut low: f64,
    config: FlipSearchConfig,
) -> Result<Option<f64>, OptionsError> {
    for _ in 0..config.iterations {
        if right - left <= config.tolerance {
            return Ok(Some(left + (right - left) / 2.0));
        }
        let middle = left + (right - left) / 2.0;
        if middle == left || middle == right {
            return Ok(None);
        }
        let current = value(snapshot, middle)?;
        if current == 0.0 {
            return Ok(Some(middle));
        }
        if current.is_sign_positive() == low.is_sign_positive() {
            left = middle;
            low = current;
        } else {
            right = middle;
        }
    }
    if right - left <= config.tolerance {
        Ok(Some(left + (right - left) / 2.0))
    } else {
        Ok(None)
    }
}
/// Search grid sign changes, skipping zero samples and retaining all refined roots.
pub fn search_flips(
    snapshot: &OptionSnapshot,
    config: FlipSearchConfig,
) -> Result<FlipResult, OptionsError> {
    let mut roots = Vec::new();
    let mut previous: Option<(f64, f64)> = None;
    let mut zero = false;
    let mut status = FlipStatus::NoCrossing;
    let mut last_price = 0.0;
    for index in 0..=config.intervals {
        let price =
            config.lower + (config.upper - config.lower) * (index as f64 / config.intervals as f64);
        if index > 0 && price <= last_price {
            status = FlipStatus::InsufficientResolution;
            break;
        }
        last_price = price;
        let current = value(snapshot, price)?;
        if current == 0.0 {
            zero = true;
            continue;
        }
        if let Some((left, low)) = previous
            && low.is_sign_positive() != current.is_sign_positive()
        {
            match refine(snapshot, left, price, low, config)? {
                Some(root) => roots.push(root),
                None => {
                    status = FlipStatus::Nonconverged;
                    break;
                }
            }
        }
        previous = Some((price, current));
    }
    if matches!(status, FlipStatus::NoCrossing) {
        status = if !roots.is_empty() {
            FlipStatus::Found
        } else if previous.is_none() && zero {
            FlipStatus::ZeroPlateau
        } else {
            FlipStatus::NoCrossing
        };
    }
    Ok(FlipResult {
        config,
        status,
        roots,
        spot: snapshot.valuation.spot,
    })
}
