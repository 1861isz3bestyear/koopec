use super::{IndicatorError, IndicatorState, check_time};
use std::collections::VecDeque;

/// Signed growth with observation and receipt timestamps in the processor's units.
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
/// Cadence of published margin growth observations.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GrowthCadence {
    Hourly,
    Daily,
}

impl GrowthCadence {
    fn seconds(self) -> i64 {
        match self {
            Self::Hourly => 3_600,
            Self::Daily => 86_400,
        }
    }
}

/// Fourteen consecutive growth observations at a fixed cadence.
#[derive(Debug, Clone, PartialEq)]
pub struct MarginMomentum {
    step: i64,
    window: VecDeque<GrowthObservation>,
    previous: Option<i64>,
}
impl Default for MarginMomentum {
    fn default() -> Self {
        Self::with_cadence(GrowthCadence::Hourly)
    }
}
impl MarginMomentum {
    pub fn new() -> Self {
        Self::default()
    }
    /// Process growth with timestamps in Unix seconds.
    pub fn with_cadence(cadence: GrowthCadence) -> Self {
        Self {
            step: cadence.seconds(),
            window: VecDeque::new(),
            previous: None,
        }
    }

    /// Preserve millisecond precision from exchange history.
    pub fn with_millisecond_cadence(cadence: GrowthCadence) -> Self {
        Self {
            step: cadence.seconds() * 1_000,
            ..Self::with_cadence(cadence)
        }
    }

    /// Process an observation atomically. A valid gap starts a new window.
    pub fn update(&mut self, point: GrowthObservation) -> Result<IndicatorState, IndicatorError> {
        let gap = check_time(
            point.observed_at,
            point.available_at,
            self.previous,
            self.step,
        )?;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn daily_momentum_requires_fourteen_consecutive_days() {
        let mut momentum = MarginMomentum::with_cadence(GrowthCadence::Daily);
        for day in 0..14 {
            let timestamp = day * 86_400;
            let state = momentum
                .update(GrowthObservation::new(timestamp, timestamp, 0.0).unwrap())
                .unwrap();
            if day < 13 {
                assert_eq!(
                    state,
                    IndicatorState::WarmingUp {
                        observed: day as usize + 1,
                        required: 14
                    }
                );
            } else {
                assert_eq!(
                    state,
                    IndicatorState::Ready {
                        value: 50.0,
                        observed_at: timestamp,
                        available_at: timestamp
                    }
                );
            }
        }
        let timestamp = 15 * 86_400;
        assert_eq!(
            momentum
                .update(GrowthObservation::new(timestamp, timestamp, 0.0).unwrap())
                .unwrap(),
            IndicatorState::Gap {
                observed: 1,
                required: 14
            }
        );
    }
}
