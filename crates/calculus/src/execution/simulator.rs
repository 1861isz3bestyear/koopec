use crate::accounts::{
    AccountError, EntryFill, ExitFill, HistoricalAccount, HistoricalAccountingRules, PositionState,
    Side,
};
use crate::types::{Micros, Price};
use rust_decimal::Decimal;
use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionError {
    InvalidCandle,
    InvalidProtection,
    InvalidSlippage,
    InvalidState,
    Chronology,
    Arithmetic,
    Account(AccountError),
}
impl fmt::Display for ExecutionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for ExecutionError {}
impl From<AccountError> for ExecutionError {
    fn from(value: AccountError) -> Self {
        Self::Account(value)
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CandleOpened {
    pub time: Micros,
    pub open: Price,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CandleCompleted {
    opened: CandleOpened,
    high: Price,
    low: Price,
    close: Price,
}
impl CandleCompleted {
    pub fn new(
        opened: CandleOpened,
        high: Price,
        low: Price,
        close: Price,
    ) -> Result<Self, ExecutionError> {
        let instrument = opened.open.instrument();
        if [high, low, close]
            .iter()
            .any(|price| price.instrument() != instrument)
            || low.value() > high.value()
            || opened.open.value() < low.value()
            || opened.open.value() > high.value()
            || close.value() < low.value()
            || close.value() > high.value()
        {
            return Err(ExecutionError::InvalidCandle);
        }
        Ok(Self {
            opened,
            high,
            low,
            close,
        })
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Protection {
    stop: Price,
    target: Price,
}
impl Protection {
    pub fn new(
        side: Side,
        entry: Price,
        stop: Price,
        target: Price,
    ) -> Result<Self, ExecutionError> {
        if stop.instrument() != entry.instrument() || target.instrument() != entry.instrument() {
            return Err(ExecutionError::InvalidProtection);
        }
        let valid = match side {
            Side::Long => stop.value() < entry.value() && entry.value() < target.value(),
            Side::Short => target.value() < entry.value() && entry.value() < stop.value(),
        };
        if !valid {
            return Err(ExecutionError::InvalidProtection);
        }
        Ok(Self { stop, target })
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EntryDecision {
    pub side: Side,
    pub price: Price,
    pub protection: Protection,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ExecutionPolicy {
    bps: Decimal,
}
impl ExecutionPolicy {
    pub fn new(bps: Decimal) -> Result<Self, ExecutionError> {
        if bps < Decimal::ZERO || bps >= Decimal::from(10_000) {
            return Err(ExecutionError::InvalidSlippage);
        }
        Ok(Self { bps })
    }
    fn fill_price(self, raw: Price, upward: bool) -> Result<Price, ExecutionError> {
        let fraction = self
            .bps
            .checked_div(Decimal::from(10_000))
            .ok_or(ExecutionError::Arithmetic)?;
        let factor = if upward {
            Decimal::ONE.checked_add(fraction)
        } else {
            Decimal::ONE.checked_sub(fraction)
        }
        .ok_or(ExecutionError::Arithmetic)?;
        let value = raw
            .value()
            .checked_mul(factor)
            .ok_or(ExecutionError::Arithmetic)?
            .round_dp(8);
        Price::from_decimal(value, raw.instrument()).map_err(|_| ExecutionError::Arithmetic)
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExitReason {
    StopLoss,
    TakeProfit,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionEvent {
    Entry(EntryFill),
    Exit { fill: ExitFill, reason: ExitReason },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct OpenProtection {
    side: Side,
    protection: Protection,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Simulator {
    policy: ExecutionPolicy,
    protection: Option<OpenProtection>,
    pending: Option<(CandleOpened, bool)>,
    last: Option<Micros>,
}
impl Simulator {
    #[must_use]
    pub const fn new(policy: ExecutionPolicy) -> Self {
        Self {
            policy,
            protection: None,
            pending: None,
            last: None,
        }
    }
    pub fn on_open(
        &mut self,
        account: &mut HistoricalAccount,
        candle: CandleOpened,
        candidate: Option<EntryDecision>,
        fill_id: u64,
        rules: &HistoricalAccountingRules,
    ) -> Result<Option<ExecutionEvent>, ExecutionError> {
        if self.pending.is_some() || self.last.is_some_and(|last| candle.time <= last) {
            return Err(ExecutionError::Chronology);
        }
        if matches!(account.position(), PositionState::Open(_)) != self.protection.is_some() {
            return Err(ExecutionError::InvalidState);
        }
        let mut next = self.clone();
        let mut updated = account.clone();
        let was_open = next.protection.is_some();
        let event = if was_open {
            next.protect(
                &mut updated,
                candle,
                (candle.open, candle.open),
                false,
                fill_id,
                rules,
            )?
        } else if let Some(decision) = candidate {
            Protection::new(
                decision.side,
                decision.price,
                decision.protection.stop,
                decision.protection.target,
            )?;
            if decision.price.instrument() != candle.open.instrument() {
                return Err(ExecutionError::InvalidProtection);
            }
            let fill = EntryFill {
                id: fill_id,
                side: decision.side,
                price: next
                    .policy
                    .fill_price(decision.price, decision.side == Side::Long)?,
                time: candle.time,
            };
            updated.apply_entry(fill, rules)?;
            next.protection = Some(OpenProtection {
                side: decision.side,
                protection: decision.protection,
            });
            Some(ExecutionEvent::Entry(fill))
        } else {
            None
        };
        next.pending = Some((candle, !was_open && next.protection.is_some()));
        *account = updated;
        *self = next;
        Ok(event)
    }
    pub fn on_complete(
        &mut self,
        account: &mut HistoricalAccount,
        candle: CandleCompleted,
        fill_id: u64,
        rules: &HistoricalAccountingRules,
    ) -> Result<Option<ExecutionEvent>, ExecutionError> {
        let (opened, entry_bar) = self.pending.ok_or(ExecutionError::Chronology)?;
        if candle.opened != opened {
            return Err(ExecutionError::Chronology);
        }
        if matches!(account.position(), PositionState::Open(_)) != self.protection.is_some() {
            return Err(ExecutionError::InvalidState);
        }
        let mut next = self.clone();
        let mut updated = account.clone();
        let event = next.protect(
            &mut updated,
            opened,
            (candle.high, candle.low),
            entry_bar,
            fill_id,
            rules,
        )?;
        next.pending = None;
        next.last = Some(opened.time);
        *self = next;
        *account = updated;
        Ok(event)
    }
    fn protect(
        &mut self,
        account: &mut HistoricalAccount,
        candle: CandleOpened,
        range: (Price, Price),
        entry_bar: bool,
        id: u64,
        rules: &HistoricalAccountingRules,
    ) -> Result<Option<ExecutionEvent>, ExecutionError> {
        let Some(position) = self.protection else {
            return Ok(None);
        };
        let (high, low) = range;
        let p = position.protection;
        if candle.open.instrument() != p.stop.instrument() {
            return Err(ExecutionError::InvalidState);
        }
        let (stop, target) = match position.side {
            Side::Long => (
                low.value() <= p.stop.value(),
                high.value() >= p.target.value(),
            ),
            Side::Short => (
                high.value() >= p.stop.value(),
                low.value() <= p.target.value(),
            ),
        };
        let (raw, reason) = if stop {
            let gap = match position.side {
                Side::Long => candle.open.value() < p.stop.value(),
                Side::Short => candle.open.value() > p.stop.value(),
            };
            (
                if gap && !entry_bar {
                    candle.open
                } else {
                    p.stop
                },
                ExitReason::StopLoss,
            )
        } else if target && !entry_bar {
            (p.target, ExitReason::TakeProfit)
        } else {
            return Ok(None);
        };
        let fill = ExitFill {
            id,
            time: candle.time,
            price: self.policy.fill_price(raw, position.side == Side::Short)?,
        };
        account.apply_exit(fill, rules)?;
        self.protection = None;
        Ok(Some(ExecutionEvent::Exit { fill, reason }))
    }
}
