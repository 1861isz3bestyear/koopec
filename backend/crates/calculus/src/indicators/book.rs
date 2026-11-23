use super::IndicatorError;

/// One book level, with quote-currency price and base-asset quantity.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BookLevel {
    price: f64,
    quantity: f64,
}
impl BookLevel {
    /// Construct a positive price and nonnegative quantity.
    pub fn new(price: f64, quantity: f64) -> Result<Self, IndicatorError> {
        if !price.is_finite() || price <= 0.0 || !quantity.is_finite() || quantity < 0.0 {
            return Err(IndicatorError::InvalidInput);
        }
        Ok(Self { price, quantity })
    }

    pub fn price(self) -> f64 {
        self.price
    }

    pub fn quantity(self) -> f64 {
        self.quantity
    }
}
fn notional(levels: &[BookLevel]) -> Result<f64, IndicatorError> {
    levels.iter().try_fold(0.0, |sum, level| {
        let next = sum + level.price * level.quantity;
        if next.is_finite() {
            Ok(next)
        } else {
            Err(IndicatorError::Arithmetic)
        }
    })
}
/// Bid share of quote notional as percentage points. An empty total is unavailable.
pub fn book_rate(bids: &[BookLevel], asks: &[BookLevel]) -> Result<Option<f64>, IndicatorError> {
    let bid = notional(bids)?;
    let ask = notional(asks)?;
    let total = bid + ask;
    if !total.is_finite() {
        return Err(IndicatorError::Arithmetic);
    }
    if total == 0.0 {
        return Ok(None);
    }
    Ok(Some((bid / total) * 100.0))
}
