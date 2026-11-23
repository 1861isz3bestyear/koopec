use super::exposure::GammaTerm;
use crate::options::{OptionSnapshot, OptionsError};

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
struct Curve(Vec<GammaTerm>);

impl Curve {
    fn new(snapshot: &OptionSnapshot) -> Result<Self, OptionsError> {
        let mut terms = Vec::with_capacity(snapshot.contracts.len());
        for item in &snapshot.contracts {
            if let Some(term) = GammaTerm::new(&item.contract, snapshot.valuation)? {
                terms.push(term);
            }
        }
        Ok(Self(terms))
    }

    fn value(&self, spot: f64) -> Result<f64, OptionsError> {
        let log_spot = spot.ln();
        let signed: f64 = self.0.iter().map(|term| term.amount(spot, log_spot)).sum();
        if signed.is_finite() {
            Ok(signed)
        } else {
            Err(OptionsError::Arithmetic)
        }
    }
}

fn refine(
    curve: &Curve,
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
        let current = curve.value(middle)?;
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
    let curve = Curve::new(snapshot)?;
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
        let current = curve.value(price)?;
        if current == 0.0 {
            zero = true;
            continue;
        }
        if let Some((left, low)) = previous
            && low.is_sign_positive() != current.is_sign_positive()
        {
            match refine(&curve, left, price, low, config)? {
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

/// Reproduce the observed-history search grid, including every observed strike.
pub fn observed_flip(snapshot: &OptionSnapshot) -> Result<Option<f64>, OptionsError> {
    let spot = snapshot.valuation.spot;
    let mut prices = Vec::with_capacity(snapshot.contracts.len() + 401);
    prices.extend(snapshot.contracts.iter().map(|item| item.contract.strike));
    prices.sort_unstable_by(f64::total_cmp);
    let lower = prices.first().map_or(spot, |price| spot.min(*price));
    let upper = prices.last().map_or(spot, |price| spot.max(*price));
    if lower == upper {
        return Ok(None);
    }
    let config = FlipSearchConfig::new(lower, upper, 400, upper * 1e-12, 64)?;
    prices.extend(
        (0..=config.intervals)
            .map(|index| lower + (upper - lower) * index as f64 / config.intervals as f64),
    );
    prices.sort_unstable_by(f64::total_cmp);
    prices.dedup();

    let curve = Curve::new(snapshot)?;
    let mut previous: Option<(f64, f64)> = None;
    let mut nearest: Option<f64> = None;
    for price in prices {
        let value = curve.value(price)?;
        if value == 0.0 {
            continue;
        }
        if let Some((left, low)) = previous
            && low.is_sign_positive() != value.is_sign_positive()
            && let Some(root) = refine(&curve, left, price, low, config)?
            && nearest.is_none_or(|nearest| (root - spot).abs() < (nearest - spot).abs())
        {
            nearest = Some(root);
        }
        previous = Some((price, value));
    }
    Ok(nearest)
}

#[cfg(test)]
mod observed_tests {
    use super::*;
    use crate::options::{IdentifiedContract, OptionContract, OptionKind, Valuation};

    #[test]
    fn observed_grid_finds_the_crossing_between_distinct_strikes() {
        let expiry = 31_536_000;
        let iv = 0.25;
        let contract = |name: &str, kind, strike| {
            IdentifiedContract::new(
                name.into(),
                OptionContract::new(kind, strike, expiry, iv, 1.0, 1.0).unwrap(),
            )
            .unwrap()
        };
        let snapshot = OptionSnapshot::new(
            0,
            0,
            Valuation::new(100.0, 0).unwrap(),
            vec![
                contract("call", OptionKind::Call, 90.0),
                contract("put", OptionKind::Put, 110.0),
            ],
        )
        .unwrap();
        let expected = (90.0_f64 * 110.0).sqrt() * (-iv * iv / 2.0).exp();
        assert!((observed_flip(&snapshot).unwrap().unwrap() - expected).abs() < 1e-8);
    }
}
