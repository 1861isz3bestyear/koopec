use super::{IndicatorError, IndicatorState, check_time};
use std::collections::VecDeque;

/// Supported regular sampling intervals.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Interval {
    FiveMinutes,
    Hourly,
}
impl Interval {
    fn seconds(self) -> i64 {
        match self {
            Self::FiveMinutes => 300,
            Self::Hourly => 3600,
        }
    }
    fn lookback(self) -> usize {
        match self {
            Self::FiveMinutes => 144,
            Self::Hourly => 12,
        }
    }
}
/// Matched positive base-asset OI and price with their latest actual receipt.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct InterestObservation {
    observed_at: i64,
    available_at: i64,
    oi: f64,
    price: f64,
}
impl InterestObservation {
    pub fn new(
        observed_at: i64,
        available_at: i64,
        oi: f64,
        price: f64,
    ) -> Result<Self, IndicatorError> {
        if available_at < observed_at
            || !oi.is_finite()
            || oi <= 0.0
            || !price.is_finite()
            || price <= 0.0
        {
            return Err(IndicatorError::InvalidInput);
        }
        Ok(Self {
            observed_at,
            available_at,
            oi,
            price,
        })
    }
}
/// Twelve-hour OI growth smoothed over three consecutive samples.
#[derive(Debug, Clone, PartialEq)]
pub struct OiMomentum {
    interval: Interval,
    window: VecDeque<InterestObservation>,
    previous: Option<i64>,
}
impl OiMomentum {
    pub fn new(interval: Interval) -> Self {
        Self {
            interval,
            window: VecDeque::new(),
            previous: None,
        }
    }
    /// Process a matched sample atomically; a gap resets the window.
    pub fn update(&mut self, point: InterestObservation) -> Result<IndicatorState, IndicatorError> {
        let gap = check_time(
            point.observed_at,
            point.available_at,
            self.previous,
            self.interval.seconds(),
        )?;
        let mut next = self.clone();
        if gap {
            next.window.clear();
        }
        next.window.push_back(point);
        let required = self.interval.lookback() + 3;
        if next.window.len() > required {
            next.window.pop_front();
        }
        next.previous = Some(point.observed_at);
        let count = next.window.len();
        let state = if count < required {
            if gap {
                IndicatorState::Gap {
                    observed: count,
                    required,
                }
            } else {
                IndicatorState::WarmingUp {
                    observed: count,
                    required,
                }
            }
        } else {
            let lookback = self.interval.lookback();
            let mut value = 0.0;
            for i in 0..3 {
                value += (next.window[lookback + i].oi / next.window[i].oi - 1.0) * (100.0 / 3.0);
            }
            if !value.is_finite() {
                return Err(IndicatorError::Arithmetic);
            }
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
