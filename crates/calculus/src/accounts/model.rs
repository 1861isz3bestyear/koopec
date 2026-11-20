use super::AccountError;
use crate::types::{Currency, Micros, Money, Price};
use rust_decimal::Decimal;
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum Side {
    Long,
    Short,
}
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct Position {
    pub side: Side,
    pub quantity: Decimal,
    pub entry_price: Price,
    pub entry_time: Micros,
    pub entry_fee: Decimal,
    pub opening_capital: Decimal,
}
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum PositionState {
    Flat,
    Open(Position),
}
/// Fee is a fraction in [0, 1). Division rounds to 16 fractional places.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct HistoricalAccountingRules {
    pub(crate) fee: Decimal,
}
impl HistoricalAccountingRules {
    pub fn new(fee: Decimal) -> Result<Self, AccountError> {
        if fee < Decimal::ZERO || fee >= Decimal::ONE {
            return Err(AccountError::InvalidFee);
        }
        Ok(Self { fee })
    }
}
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct HistoricalAccount {
    pub(crate) cash: Decimal,
    pub(crate) currency: Currency,
    pub(crate) position: PositionState,
    pub(crate) realized_pnl: Decimal,
}
impl HistoricalAccount {
    #[must_use]
    pub fn new(cash: Money) -> Self {
        Self {
            cash: cash.amount(),
            currency: cash.currency(),
            position: PositionState::Flat,
            realized_pnl: Decimal::ZERO,
        }
    }
    #[must_use]
    pub const fn cash(&self) -> Decimal {
        self.cash
    }
    #[must_use]
    pub const fn currency(&self) -> Currency {
        self.currency
    }
    #[must_use]
    pub const fn position(&self) -> PositionState {
        self.position
    }
    #[must_use]
    pub const fn realized_pnl(&self) -> Decimal {
        self.realized_pnl
    }
}
