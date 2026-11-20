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
