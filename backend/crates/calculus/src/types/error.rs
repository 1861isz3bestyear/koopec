use std::fmt;
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TypeParseError {
    NonPositive,
    Negative,
    InvalidDecimal,
    TooPrecise,
}
impl fmt::Display for TypeParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for TypeParseError {}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ArithmeticError {
    UnitMismatch,
    Overflow,
    InsufficientAmount,
}
impl fmt::Display for ArithmeticError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for ArithmeticError {}
