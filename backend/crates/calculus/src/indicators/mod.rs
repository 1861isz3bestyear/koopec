//! Pure market indicators. Timestamps are caller-supplied Unix seconds.
mod book;
mod margin;
mod oi;
mod pivots;

pub use book::{BookLevel, book_rate};
pub use margin::{GrowthCadence, GrowthObservation, MarginMomentum};
pub use oi::{InterestObservation, Interval, OiMomentum};
pub use pivots::{
    Comparison, Pivot, PivotKind, PivotPoint, SwingRelation, compare_pivots, detect_pivot,
};

/// Invalid observations, chronological errors, or arithmetic failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IndicatorError {
    InvalidInput,
    OutOfOrder,
    Arithmetic,
}
impl std::fmt::Display for IndicatorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for IndicatorError {}

/// State after processing a valid observation.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum IndicatorState {
    WarmingUp {
        observed: usize,
        required: usize,
    },
    Gap {
        observed: usize,
        required: usize,
    },
    Ready {
        value: f64,
        observed_at: i64,
        available_at: i64,
    },
}

fn check_time(
    observed_at: i64,
    available_at: i64,
    previous: Option<i64>,
    step: i64,
) -> Result<bool, IndicatorError> {
    if available_at < observed_at {
        return Err(IndicatorError::InvalidInput);
    }
    let Some(last) = previous else {
        return Ok(false);
    };
    let delta = observed_at
        .checked_sub(last)
        .ok_or(IndicatorError::Arithmetic)?;
    if delta <= 0 {
        return Err(IndicatorError::OutOfOrder);
    }
    Ok(delta != step)
}
