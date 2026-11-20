use calculus::types::{Asset, Currency, Money, Price, Quantity, Ticker, TypeParseError, Unit};

#[test]
fn money_parses_exact_nonnegative_values_at_precision_boundaries() {
    for text in [
        "0",
        "0.0000000000000000000000000000",
        "0.00000001",
        "0.000000001",
        "0.0000000000000000000000000001",
        "79228162514264337593543950335",
    ] {
        let amount = Money::parse(text, Currency::USDT).unwrap();
        assert_eq!(amount.amount().to_string(), text);
        assert_eq!(amount.currency(), Currency::USDT);
    }
}

#[test]
fn money_rejects_negative_invalid_or_unrepresentable_values() {
    for text in ["-0", "-0.000000000", "-1"] {
        assert_eq!(
            Money::parse(text, Currency::USDT),
            Err(TypeParseError::Negative),
            "{text}"
        );
    }
    for text in [
        "",
        "NaN",
        "1.2.3",
        "0.00000000000000000000000000001",
        "79228162514264337593543950336",
    ] {
        assert_eq!(
            Money::parse(text, Currency::USDT),
            Err(TypeParseError::InvalidDecimal),
            "{text}"
        );
    }
}

#[test]
fn exact_product_can_be_parsed_back_as_money() {
    let price = Price::parse("0.00000001", Ticker::new(Asset::BTC, Currency::USDT)).unwrap();
    let quantity = Quantity::parse("0.00000001", Unit::Asset(Asset::BTC)).unwrap();
    let product = (quantity * price).unwrap();
    assert_eq!(
        product,
        Money::parse("0.0000000000000001", Currency::USDT).unwrap()
    );
}
