use super::TypeParseError;
use rust_decimal::Decimal;
pub const MAX_SCALE: u32 = 8;
pub fn parse_decimal(text: &str, allow_zero: bool) -> Result<Decimal, TypeParseError> {
    let value = Decimal::from_str_exact(text).map_err(|_| TypeParseError::InvalidDecimal)?;
    if text.starts_with('-') || value.is_sign_negative() {
        return Err(TypeParseError::Negative);
    }
    if !allow_zero && value.is_zero() {
        return Err(TypeParseError::NonPositive);
    }
    if value.scale() > MAX_SCALE {
        return Err(TypeParseError::TooPrecise);
    }
    Ok(value)
}
