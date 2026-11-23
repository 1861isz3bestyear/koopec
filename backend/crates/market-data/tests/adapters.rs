//! Adapter conditions: exchange errors, timestamps, invalid levels, and duplicate growth.
use calculus::indicators::book_rate;
use market_data::{Source, book, growth, growth_observation, loan_rate, request};

#[test]
fn requests_cover_supported_sources_and_reject_unknown_assets() {
    for source in [
        Source::BybitBook,
        Source::BitgetHourlyGrowth,
        Source::BitgetDailyGrowth,
        Source::BitgetLoanRate,
    ] {
        let result = request(source, "BTC").unwrap();
        assert!(result.url.starts_with("https://"));
        assert!(request(source, "DOGE").is_err());
    }
    assert!(
        request(Source::BitgetDailyGrowth, "ETH")
            .unwrap()
            .parameters
            .contains(&("period", "30d".into()))
    );
}

#[test]
fn book_checks_data_and_receipt_freshness() {
    let payload =
        r#"{"retCode":0,"result":{"s":"BTCUSDT","ts":1000,"b":[["99","2"]],"a":[["101","1"]]}}"#;
    let parsed = book(payload, "BTC", 11000).unwrap();
    assert!(
        (book_rate(&parsed.bids, &parsed.asks).unwrap().unwrap() - 100.0 * 198.0 / 299.0).abs()
            < 1e-10
    );
    assert!(book(payload, "BTC", 11001).is_err());
    assert!(book(payload, "BTC", 999).is_err());
    assert!(book(payload, "ETH", 1000).is_err());
    assert!(book(&payload.replace("101", "98"), "BTC", 1000).is_err());
    assert!(book(&payload.replace("\"99\"", "\"NaN\""), "BTC", 1000).is_err());
    assert!(
        book(
            &payload.replace("\"retCode\":0", "\"retCode\":1"),
            "BTC",
            1000
        )
        .is_err()
    );
}

#[test]
fn growth_sorts_deduplicates_and_rejects_conflicts_and_future_records() {
    let payload = r#"{"code":"00000","data":[{"ts":"2000","growthRate":"-0.2"},{"ts":"1000","growthRate":"0.1"},{"ts":"1000","growthRate":"0.1"}]}"#;
    assert_eq!(
        growth(payload, 2000).unwrap(),
        vec![(1000, 0.1), (2000, -0.2)]
    );
    assert!(growth(payload, 1999).is_err());
    assert!(growth(&payload.replacen("0.1", "0.3", 1), 2000).is_err());
    assert!(growth("{}", 2000).is_err());
    assert!(growth_observation(1000, 1001, 0.1).is_ok());
    assert!(growth_observation(1001, 2000, 0.1).is_err());
}

#[test]
fn loan_rates_are_nonnegative_and_exchange_errors_fail() {
    let payload = r#"{"code":"00000","requestTime":1000,"data":{"dailyInterest":"0.01","annualInterest":"0.1"}}"#;
    let quote = loan_rate(payload).unwrap();
    assert_eq!(quote.daily, 0.01);
    assert!(loan_rate(&payload.replace("0.01", "-0.01")).is_err());
    assert!(loan_rate(&payload.replace("00000", "40000")).is_err());
}
