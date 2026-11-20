use super::{Ticker, TypeParseError, parse::parse_decimal};
use rust_decimal::Decimal;
use std::cmp::Ordering;
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct Price {
    value: Decimal,
    instrument: Ticker,
}
impl Price {
    pub fn parse(text: &str, instrument: Ticker) -> Result<Self, TypeParseError> {
        Ok(Self {
            value: parse_decimal(text, false)?,
            instrument,
        })
    }
    /// Construct a positive price from a calculated decimal with at most eight fractional places.
    pub fn from_decimal(value: Decimal, instrument: Ticker) -> Result<Self, TypeParseError> {
        if value <= Decimal::ZERO {
            return Err(TypeParseError::NonPositive);
        }
        if value.scale() > 8 {
            return Err(TypeParseError::TooPrecise);
        }
        Ok(Self { value, instrument })
    }
    #[must_use]
    pub const fn value(self) -> Decimal {
        self.value
    }
    #[must_use]
    pub const fn instrument(self) -> Ticker {
        self.instrument
    }
}
impl PartialOrd for Price {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        (self.instrument == other.instrument).then(|| self.value.cmp(&other.value))
    }
}
