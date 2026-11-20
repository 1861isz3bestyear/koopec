use super::{
    AccountError, EntryFill, ExitFill, ExitSettlement, HistoricalAccount,
    HistoricalAccountingRules, MarkedEquity, Position, PositionState, Side,
};
use crate::types::Price;
use rust_decimal::Decimal;

fn mul(a: Decimal, b: Decimal) -> Result<Decimal, AccountError> {
    let a = a.normalize();
    let b = b.normalize();
    let mantissa = a
        .mantissa()
        .checked_mul(b.mantissa())
        .ok_or(AccountError::Arithmetic)?;
    let scale = a
        .scale()
        .checked_add(b.scale())
        .ok_or(AccountError::Arithmetic)?;
    Decimal::try_from_i128_with_scale(mantissa, scale).map_err(|_| AccountError::Arithmetic)
}
fn add(a: Decimal, b: Decimal) -> Result<Decimal, AccountError> {
    a.checked_add(b).ok_or(AccountError::Arithmetic)
}
fn sub(a: Decimal, b: Decimal) -> Result<Decimal, AccountError> {
    a.checked_sub(b).ok_or(AccountError::Arithmetic)
}
impl HistoricalAccount {
    /// Opens a position with all available capital; quantity rounds to 16 places.
    pub fn apply_entry(
        &mut self,
        fill: EntryFill,
        rules: &HistoricalAccountingRules,
    ) -> Result<Position, AccountError> {
        if self.position != PositionState::Flat {
            return Err(AccountError::AlreadyOpen);
        }
        if self.cash.is_zero() {
            return Err(AccountError::EmptyBalance);
        }
        if fill.price.instrument().currency() != self.currency {
            return Err(AccountError::InstrumentMismatch);
        }
        let fee = mul(self.cash, rules.fee)?;
        let quantity = sub(self.cash, fee)?
            .checked_div(fill.price.value())
            .ok_or(AccountError::Arithmetic)?
            .round_dp(16);
        if quantity <= Decimal::ZERO {
            return Err(AccountError::Arithmetic);
        }
        let position = Position {
            side: fill.side,
            quantity,
            entry_price: fill.price,
            entry_time: fill.time,
            entry_fee: fee,
            opening_capital: self.cash,
        };
        self.position = PositionState::Open(position);
        self.cash = Decimal::ZERO;
        Ok(position)
    }
    /// Closes the entire position. A negative resulting cash balance is rejected.
    pub fn apply_exit(
        &mut self,
        fill: ExitFill,
        rules: &HistoricalAccountingRules,
    ) -> Result<ExitSettlement, AccountError> {
        let PositionState::Open(position) = self.position else {
            return Err(AccountError::NoPosition);
        };
        if fill.price.instrument() != position.entry_price.instrument() {
            return Err(AccountError::InstrumentMismatch);
        }
        if fill.time < position.entry_time {
            return Err(AccountError::TimeOrder);
        }
        let turnover = mul(position.quantity, fill.price.value())?;
        let fee = mul(turnover, rules.fee)?;
        let cash = match position.side {
            Side::Long => sub(turnover, fee)?,
            Side::Short => sub(
                sub(
                    add(
                        position.opening_capital,
                        mul(
                            position.quantity,
                            sub(position.entry_price.value(), fill.price.value())?,
                        )?,
                    )?,
                    position.entry_fee,
                )?,
                fee,
            )?,
        };
        if cash < Decimal::ZERO {
            return Err(AccountError::NegativeCash);
        }
        let pnl = sub(cash, position.opening_capital)?;
        let total = add(self.realized_pnl, pnl)?;
        self.cash = cash;
        self.realized_pnl = total;
        self.position = PositionState::Flat;
        Ok(ExitSettlement {
            fill_id: fill.id,
            fee,
            pnl,
            cash,
        })
    }
    pub fn mark(&self, price: Price) -> Result<MarkedEquity, AccountError> {
        let PositionState::Open(position) = self.position else {
            return Ok(MarkedEquity {
                equity: self.cash,
                signed_quantity: Decimal::ZERO,
            });
        };
        if price.instrument() != position.entry_price.instrument() {
            return Err(AccountError::InstrumentMismatch);
        }
        match position.side {
            Side::Long => Ok(MarkedEquity {
                equity: mul(position.quantity, price.value())?,
                signed_quantity: position.quantity,
            }),
            Side::Short => Ok(MarkedEquity {
                equity: add(
                    sub(position.opening_capital, position.entry_fee)?,
                    mul(
                        position.quantity,
                        sub(position.entry_price.value(), price.value())?,
                    )?,
                )?,
                signed_quantity: -position.quantity,
            }),
        }
    }
}
