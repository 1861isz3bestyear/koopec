use std::fmt;
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AccountError {
    InvalidFee,
    EmptyBalance,
    AlreadyOpen,
    NoPosition,
    InstrumentMismatch,
    TimeOrder,
    Arithmetic,
    NegativeCash,
}
impl fmt::Display for AccountError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for AccountError {}
