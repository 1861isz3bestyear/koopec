use std::time::Duration;
/// Signed Unix timestamp in microseconds. Range validation belongs to the input boundary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default)]
pub struct Micros(pub i64);
impl Micros {
    #[must_use]
    pub const fn new(value: i64) -> Self {
        Self(value)
    }
    #[must_use]
    pub const fn get(self) -> i64 {
        self.0
    }
}
impl std::fmt::Display for Micros {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}
/// Nonzero maximum age in microseconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DurationMicros(std::num::NonZeroU64);
impl DurationMicros {
    #[must_use]
    pub const fn new(value: u64) -> Option<Self> {
        match std::num::NonZeroU64::new(value) {
            Some(v) => Some(Self(v)),
            None => None,
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Evidence {
    pub observed_at: Micros,
    pub calculatable: bool,
}
impl Evidence {
    #[must_use]
    pub const fn new(observed_at: Micros, calculatable: bool) -> Self {
        Self {
            observed_at,
            calculatable,
        }
    }
    #[must_use]
    pub const fn uncalculatable(observed_at: Micros) -> Self {
        Self::new(observed_at, false)
    }
}
#[must_use]
pub fn is_fresh(point: Evidence, now: Micros, max_age: DurationMicros) -> bool {
    if !point.calculatable {
        return false;
    }
    let Some(age) = now
        .0
        .checked_sub(point.observed_at.0)
        .and_then(|age| u64::try_from(age).ok())
    else {
        return false;
    };
    Duration::from_micros(age) <= Duration::from_micros(max_age.0.get())
}
