use super::Side;
use crate::types::{Micros, Price};
use rust_decimal::Decimal;
/// Prices are execution prices after any simulation slippage.
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct EntryFill {
    pub id: u64,
    pub side: Side,
    pub price: Price,
    pub time: Micros,
}
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct ExitFill {
    pub id: u64,
    pub price: Price,
    pub time: Micros,
}
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct ExitSettlement {
    pub fill_id: u64,
    pub fee: Decimal,
    pub pnl: Decimal,
    pub cash: Decimal,
}
#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct MarkedEquity {
    pub equity: Decimal,
    pub signed_quantity: Decimal,
}
