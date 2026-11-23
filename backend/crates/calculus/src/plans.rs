//! Pure classification of a positive-GEX tunnel.

/// Validated tunnel bounds and flip, expressed in the same price units.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PositiveTunnel {
    lower: f64,
    upper: f64,
    flip: f64,
}
/// Tunnel classification for the positive-GEX strategy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TunnelState {
    Tight,
    FlipInside,
    FlipBelow,
}
/// Invalid tunnel or width.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvalidTunnel;
impl PositiveTunnel {
    /// Require positive finite prices, ordered bounds, and an upper bound above flip.
    pub fn new(lower: f64, upper: f64, flip: f64) -> Result<Self, InvalidTunnel> {
        if ![lower, upper, flip]
            .into_iter()
            .all(|x| x.is_finite() && x > 0.0)
            || lower > upper
            || upper <= flip
        {
            return Err(InvalidTunnel);
        }
        Ok(Self { lower, upper, flip })
    }
    /// Classify using inclusive tight-width and lower-bound comparisons.
    pub fn classify(self, tight_width: f64) -> Result<TunnelState, InvalidTunnel> {
        if !tight_width.is_finite() || tight_width < 0.0 {
            return Err(InvalidTunnel);
        }
        let ratio = self.upper / self.lower - 1.0;
        if !ratio.is_finite() {
            return Err(InvalidTunnel);
        }
        Ok(if ratio <= tight_width {
            TunnelState::Tight
        } else if self.lower <= self.flip {
            TunnelState::FlipInside
        } else {
            TunnelState::FlipBelow
        })
    }
}

/// Receipt and exclusive expiry of an ordered replay plan, in Unix microseconds.
#[derive(Debug, Clone, Copy)]
pub struct PlanWindow {
    pub available: i64,
    pub expires: i64,
}

/// Assign the newest observable plan to each opening quote. Expired plans leave a gap.
pub fn active_plan_indices(
    plans: &[PlanWindow],
    quotes: &[i64],
) -> Result<Vec<Option<usize>>, InvalidTunnel> {
    if plans.iter().any(|plan| plan.expires <= plan.available)
        || plans
            .windows(2)
            .any(|pair| pair[0].available >= pair[1].available)
    {
        return Err(InvalidTunnel);
    }
    Ok(quotes
        .iter()
        .map(|quote| {
            plans
                .partition_point(|plan| plan.available <= *quote)
                .checked_sub(1)
                .filter(|&index| *quote < plans[index].expires)
        })
        .collect())
}

impl PositiveTunnel {
    /// An eligible wall gives a single direction. Overlapping eligible walls are neutral.
    pub fn direction(self, state: TunnelState, price: f64, proximity: f64) -> i8 {
        if !price.is_finite() || price <= self.flip || !proximity.is_finite() || proximity < 0.0 {
            return 0;
        }
        let long =
            state != TunnelState::FlipInside && (price / self.lower - 1.0).abs() <= proximity;
        let short = state != TunnelState::Tight && (price / self.upper - 1.0).abs() <= proximity;
        i8::from(long) - i8::from(short)
    }
}
