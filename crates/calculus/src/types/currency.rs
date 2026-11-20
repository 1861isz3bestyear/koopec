#[derive(Debug, Clone, Copy, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub struct Ticker {
    currency: Currency,
    asset: Asset,
}
impl Ticker {
    #[must_use]
    pub const fn new(asset: Asset, currency: Currency) -> Self {
        Self { currency, asset }
    }
    #[must_use]
    pub const fn asset(self) -> Asset {
        self.asset
    }
    #[must_use]
    pub const fn currency(self) -> Currency {
        self.currency
    }
}
#[derive(Debug, Clone, Copy, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub enum Unit {
    Asset(Asset),
    Currency(Currency),
}
#[derive(Debug, Clone, Copy, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub enum Currency {
    USDT,
}
#[derive(Debug, Clone, Copy, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub enum Asset {
    BTC,
}
