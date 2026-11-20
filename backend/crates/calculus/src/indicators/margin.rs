use super::{IndicatorError, IndicatorState, check_time};
use std::collections::VecDeque;

/// Signed growth at an observed time, with actual receipt time in Unix seconds.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct GrowthObservation {
    observed_at: i64,
    available_at: i64,
    growth: f64,
}
impl GrowthObservation {
    pub fn new(observed_at: i64, available_at: i64, growth: f64) -> Result<Self, IndicatorError> {
        if available_at < observed_at || !growth.is_finite() {
            return Err(IndicatorError::InvalidInput);
        }
        Ok(Self {
            observed_at,
            available_at,
            growth,
        })
    }
}
/// Fourteen consecutive hourly growth observations.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct MarginMomentum {
    window: VecDeque<GrowthObservation>,
    previous: Option<i64>,
}
impl MarginMomentum {
    pub fn new() -> Self {
        Self::default()
    }
    /// Process an observation atomically. A valid gap starts a new window.
    pub fn update(&mut self, point: GrowthObservation) -> Result<IndicatorState, IndicatorError> {
        let gap = check_time(point.observed_at, point.available_at, self.previous, 3600)?;
        let mut next = self.clone();
        if gap {
            next.window.clear();
        }
        next.window.push_back(point);
        if next.window.len() > 14 {
            next.window.pop_front();
        }
        next.previous = Some(point.observed_at);
        let count = next.window.len();
        let state = if count < 14 {
            if gap {
                IndicatorState::Gap {
                    observed: count,
                    required: 14,
                }
            } else {
                IndicatorState::WarmingUp {
                    observed: count,
                    required: 14,
                }
            }
        } else {
            let scale = next
                .window
                .iter()
                .map(|p| p.growth.abs())
                .fold(0.0, f64::max);
            let (mut positive, mut total) = (0.0, 0.0);
            if scale > 0.0 {
                for p in &next.window {
                    let x = p.growth / scale;
                    total += x.abs();
                    positive += x.max(0.0);
                }
            }
            let value = if total == 0.0 {
                50.0
            } else {
                100.0 * positive / total
            };
            IndicatorState::Ready {
                value,
                observed_at: point.observed_at,
                available_at: next
                    .window
                    .iter()
                    .map(|p| p.available_at)
                    .max()
                    .ok_or(IndicatorError::Arithmetic)?,
            }
        };
        *self = next;
        Ok(state)
    }
}
