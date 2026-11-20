use super::{
    ArithmeticError, Currency, Price, Quantity, TypeParseError, Unit, parse::parse_decimal,
};
use rust_decimal::Decimal;
use std::{
    cmp::Ordering,
    ops::{Add, Mul, Sub},
};
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct Money {
    amount: Decimal,
    currency: Currency,
}
impl Money {
    pub fn parse(text: &str, currency: Currency) -> Result<Self, TypeParseError> {
        Ok(Self {
            amount: parse_decimal(text, true)?,
            currency,
        })
    }
    #[must_use]
    pub const fn amount(self) -> Decimal {
        self.amount
    }
    #[must_use]
    pub const fn currency(self) -> Currency {
        self.currency
    }
}
impl PartialOrd for Money {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        (self.currency == other.currency).then(|| self.amount.cmp(&other.amount))
    }
}
impl Add for Money {
    type Output = Result<Self, ArithmeticError>;
    fn add(self, rhs: Self) -> Self::Output {
        if self.currency != rhs.currency {
            return Err(ArithmeticError::UnitMismatch);
        }
        Ok(Self {
            amount: self
                .amount
                .checked_add(rhs.amount)
                .ok_or(ArithmeticError::Overflow)?,
            currency: self.currency,
        })
    }
}
impl Sub for Money {
    type Output = Result<Self, ArithmeticError>;
    fn sub(self, rhs: Self) -> Self::Output {
        if self.currency != rhs.currency {
            return Err(ArithmeticError::UnitMismatch);
        }
        if self.amount < rhs.amount {
            return Err(ArithmeticError::InsufficientAmount);
        }
        Ok(Self {
            amount: self
                .amount
                .checked_sub(rhs.amount)
                .ok_or(ArithmeticError::Overflow)?,
            currency: self.currency,
        })
    }
}
impl Mul<Price> for Quantity {
    type Output = Result<Money, ArithmeticError>;
    fn mul(self, price: Price) -> Self::Output {
        if self.unit() != Unit::Asset(price.instrument().asset()) {
            return Err(ArithmeticError::UnitMismatch);
        }
        Ok(Money {
            amount: self
                .value()
                .checked_mul(price.value())
                .ok_or(ArithmeticError::Overflow)?,
            currency: price.instrument().currency(),
        })
    }
}
