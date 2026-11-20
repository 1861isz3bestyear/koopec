use super::{TypeParseError, Unit, parse::parse_decimal};
use rust_decimal::Decimal;
use std::cmp::Ordering;
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct Quantity {
    value: Decimal,
    unit: Unit,
}
impl Quantity {
    pub fn parse(text: &str, unit: Unit) -> Result<Self, TypeParseError> {
        Ok(Self {
            value: parse_decimal(text, false)?,
            unit,
        })
    }
    #[must_use]
    pub const fn value(self) -> Decimal {
        self.value
    }
    #[must_use]
    pub const fn unit(self) -> Unit {
        self.unit
    }
}
impl PartialOrd for Quantity {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        (self.unit == other.unit).then(|| self.value.cmp(&other.value))
    }
}
