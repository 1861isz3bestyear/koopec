//! Risk-based examples: decimal boundaries, freshness decisions and journal recovery.

use calculus::types::{
    Asset, CommitSeq, Currency, Cursor, DurationMicros, Evidence, Journal, JournalError,
    JournalRow, Micros, Money, Price, Projection, Quantity, RowId, RowPayload, Ticker,
    TypeParseError, Unit, is_fresh,
};

#[test]
fn decimal_input_partitions_preserve_financial_boundaries() {
    let ticker = Ticker::new(Asset::BTC, Currency::USDT);
    let unit = Unit::Asset(Asset::BTC);
    // Eight decimal places are accepted; a ninth is rejected for all inputs.
    assert!(Money::parse("0.00000001", Currency::USDT).is_ok());
    assert!(Price::parse("0.00000001", ticker).is_ok());
    assert!(Quantity::parse("0.00000001", unit).is_ok());
    assert_eq!(
        Money::parse("0.000000001", Currency::USDT),
        Err(TypeParseError::TooPrecise)
    );
    assert_eq!(
        Price::parse("0.000000001", ticker),
        Err(TypeParseError::TooPrecise)
    );
    assert_eq!(
        Quantity::parse("0.000000001", unit),
        Err(TypeParseError::TooPrecise)
    );
    // A zero balance is valid; a zero price or order quantity is not.
    assert!(Money::parse("0", Currency::USDT).is_ok());
    assert_eq!(Price::parse("0", ticker), Err(TypeParseError::NonPositive));
    assert_eq!(Quantity::parse("0", unit), Err(TypeParseError::NonPositive));
    assert_eq!(
        Money::parse("-1", Currency::USDT),
        Err(TypeParseError::Negative)
    );
    assert_eq!(
        Quantity::parse("bad", unit),
        Err(TypeParseError::InvalidDecimal)
    );
}

#[test]
fn freshness_decision_table_checks_calculatability_and_age() {
    let limit = DurationMicros::new(10).unwrap();
    // (calculatable, now, expected): future, fresh, boundary and expired.
    for (calculatable, now, expected) in [
        (true, 99, false),
        (true, 100, true),
        (true, 109, true),
        (true, 110, true),
        (true, 111, false),
        (false, 100, false),
        (false, 110, false),
        (false, 111, false),
    ] {
        assert_eq!(
            is_fresh(Evidence::new(Micros(100), calculatable), Micros(now), limit),
            expected,
            "calculatable={calculatable}, now={now}"
        );
    }
}

fn observation(id: u64, sequence: u64, value: i64) -> JournalRow {
    JournalRow {
        id: RowId(id),
        commit_seq: CommitSeq(sequence),
        available_at: Micros(1),
        payload: RowPayload::Observation { value },
    }
}

#[test]
fn rejected_batch_does_not_publish_rows_or_consume_ids_or_sequence() {
    let mut journal = Journal::new();
    journal.commit(vec![observation(1, 1, 10)]).unwrap();
    let invalid = JournalRow {
        id: RowId(3),
        commit_seq: CommitSeq(2),
        available_at: Micros(1),
        payload: RowPayload::Recalculation {
            corrects: RowId(99),
            value: 30,
        },
    };
    assert_eq!(
        journal.commit(vec![observation(2, 2, 20), invalid]),
        Err(JournalError::MissingObservation)
    );
    assert_eq!(
        journal.read_after(Cursor::start()),
        vec![&observation(1, 1, 10)]
    );
    // Reuse the rejected sequence and both IDs to prove the failed commit was atomic.
    journal
        .commit(vec![observation(3, 2, 30), observation(2, 2, 20)])
        .unwrap();
    let rows = journal.read_after(Cursor::start());
    assert_eq!(
        rows.iter().map(|row| row.id).collect::<Vec<_>>(),
        vec![RowId(1), RowId(2), RowId(3)]
    );
    let mut projection = Projection::default();
    projection.update(&journal).unwrap();
    assert_eq!(
        (
            projection.get(RowId(1)),
            projection.get(RowId(2)),
            projection.get(RowId(3))
        ),
        (Some(10), Some(20), Some(30))
    );
    let before = projection.clone();
    projection.update(&journal).unwrap();
    assert_eq!(projection, before);
}
