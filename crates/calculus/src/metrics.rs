//! Explicit return calculation for one independently funded account.
use rust_decimal::Decimal;

/// Invalid capital or an unrepresentable calculation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReturnError {
    InvalidCapital,
    Arithmetic,
}
/// Fractional return relative to positive initial capital; zero is breakeven.
pub fn net_return(initial: Decimal, final_equity: Decimal) -> Result<Decimal, ReturnError> {
    if initial <= Decimal::ZERO || final_equity < Decimal::ZERO {
        return Err(ReturnError::InvalidCapital);
    }
    final_equity
        .checked_sub(initial)
        .and_then(|pnl| pnl.checked_div(initial))
        .ok_or(ReturnError::Arithmetic)
}
