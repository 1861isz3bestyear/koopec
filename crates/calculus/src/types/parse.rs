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

#[cfg(test)]
mod tests {
    use super::{TypeParseError, parse_decimal};

    #[test]
    fn decimal_validation_distinguishes_zero_sign_and_precision() {
        for (input, allow_zero, expected) in [
            ("0", true, None),
            ("0", false, Some(TypeParseError::NonPositive)),
            ("-0", true, Some(TypeParseError::Negative)),
            ("0.00000001", false, None),
            ("0.000000001", false, Some(TypeParseError::TooPrecise)),
            ("invalid", true, Some(TypeParseError::InvalidDecimal)),
        ] {
            assert_eq!(parse_decimal(input, allow_zero).err(), expected, "{input}");
        }
    }
}
