use market_data::{Source, deribit, request};
use serde_json::{Value, json};

fn instrument(name: &str, side: &str) -> Value {
    json!({
        "instrument_name": name, "base_currency": "ETH", "kind": "option",
        "option_type": side, "is_active": true, "expiration_timestamp": 1_800_000_000_125_i64,
        "strike": 2_000, "contract_size": 0.25
    })
}

#[test]
fn requests_share_asset_and_only_instruments_exclude_expired() {
    let instruments = request(Source::DeribitInstruments, "ETH").unwrap();
    let summary = request(Source::DeribitSummary, "ETH").unwrap();
    let index = request(Source::DeribitIndex, "ETH").unwrap();
    assert!(instruments.url.ends_with("/get_instruments"));
    assert!(summary.url.ends_with("/get_book_summary_by_currency"));
    assert!(index.url.ends_with("/get_index_price"));
    assert_eq!(instruments.parameters[..2], summary.parameters);
    assert_eq!(instruments.parameters[2], ("expired", "false".into()));
    assert_eq!(index.parameters, [("index_name", "eth_usd".into())]);
    assert!(request(Source::DeribitInstruments, "DOGE").is_err());
}

#[test]
fn chain_preserves_wire_order_millisecond_expiry_and_zero_interest() {
    let mut inactive = instrument("inactive", "put");
    inactive["is_active"] = json!(false);
    let instruments = json!([instrument("Z", "call"), inactive, instrument("A", "put")]);
    let quotes = json!([
        {"instrument_name": "A", "open_interest": 2, "mark_iv": 50},
        {"instrument_name": "Z", "open_interest": 0, "mark_iv": 25}
    ]);
    let chain = deribit::normalize_chain(&instruments, &quotes, "ETH").unwrap();
    assert_eq!(
        chain
            .iter()
            .map(|c| c.instrument.as_str())
            .collect::<Vec<_>>(),
        ["Z", "A"]
    );
    assert_eq!(chain[0].expiry_ms, 1_800_000_000_125);
    assert_eq!(chain[0].open_interest, 0.0);
    assert_eq!(chain[0].side.as_str(), "call");
    assert_eq!(chain[1].open_interest, 8.0);
    assert_eq!(chain[1].iv, 0.5);
    assert_eq!(chain[1].side.as_str(), "put");
}

#[test]
fn invalid_envelopes_and_incomplete_or_invalid_chains_are_rejected() {
    assert_eq!(
        deribit::spot(&json!({"result":{"index_price": 2000}})).unwrap(),
        2000.0
    );
    for envelope in [
        json!({}),
        json!({"error":null,"result":{"index_price": 2000}}),
        json!({"result":{"index_price":"2000"}}),
    ] {
        assert!(deribit::spot(&envelope).is_err());
    }

    let contract = instrument("A", "put");
    let quotes = json!([{"instrument_name": "A", "open_interest": 2, "mark_iv": 50}]);
    assert!(deribit::normalize_chain(&json!([&contract]), &quotes, "BTC").is_err());
    assert!(deribit::normalize_chain(&json!([&contract]), &quotes, "XRP").is_err());
    for invalid in [
        json!(null),
        json!([{ "is_active": true }]),
        json!([&contract, &contract]),
    ] {
        assert!(deribit::normalize_chain(&invalid, &quotes, "ETH").is_err());
    }
    for (field, value) in [
        ("is_active", json!(1)),
        ("kind", json!("future")),
        ("option_type", json!("other")),
        ("strike", json!(0)),
    ] {
        let mut invalid = contract.clone();
        invalid[field] = value;
        assert!(deribit::normalize_chain(&json!([invalid]), &quotes, "ETH").is_err());
    }
    assert!(deribit::normalize_chain(&json!([&contract]), &json!([]), "ETH").is_err());
}
