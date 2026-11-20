use calculus::types::{
    ArithmeticError, Asset, CommitSeq, Currency, Cursor, DurationMicros, Evidence, Journal,
    JournalError, JournalRow, Micros, Money, Price, Projection, Quantity, RowId, RowPayload,
    Ticker, TypeParseError, Unit, is_fresh,
};

fn row(id: u64, seq: u64, payload: RowPayload) -> JournalRow {
    JournalRow {
        id: RowId(id),
        commit_seq: CommitSeq(seq),
        available_at: Micros(1),
        payload,
    }
}
fn obs(id: u64, seq: u64) -> JournalRow {
    row(id, seq, RowPayload::Observation { value: id as i64 })
}

#[test]
fn money_and_units() {
    let ticker = Ticker::new(Asset::BTC, Currency::USDT);
    let price = Price::parse("100.5", ticker).unwrap();
    let quantity = Quantity::parse("2", Unit::Asset(Asset::BTC)).unwrap();
    let result = (quantity * price).unwrap();
    assert_eq!(result, Money::parse("201", Currency::USDT).unwrap());
    assert_eq!(
        Quantity::parse("2", Unit::Currency(Currency::USDT)).unwrap() * price,
        Err(ArithmeticError::UnitMismatch)
    );
    assert_eq!(
        Money::parse("1", Currency::USDT).unwrap() - result,
        Err(ArithmeticError::InsufficientAmount)
    );
    assert_eq!(
        (Money::parse("1", Currency::USDT).unwrap() + Money::parse("2", Currency::USDT).unwrap())
            .unwrap(),
        Money::parse("3", Currency::USDT).unwrap()
    );
    assert_eq!(Price::parse("0", ticker), Err(TypeParseError::NonPositive));
    assert_eq!(Price::parse("-0.0", ticker), Err(TypeParseError::Negative));
    assert_eq!(
        Price::parse("0.000000001", ticker),
        Err(TypeParseError::TooPrecise)
    );
    assert_eq!(
        Price::parse("abc", ticker),
        Err(TypeParseError::InvalidDecimal)
    );
}

#[test]
fn evidence_boundaries() {
    let age = DurationMicros::new(10).unwrap();
    assert!(DurationMicros::new(0).is_none());
    assert!(is_fresh(Evidence::new(Micros(10), true), Micros(20), age));
    assert!(!is_fresh(Evidence::new(Micros(10), true), Micros(21), age));
    assert!(!is_fresh(Evidence::new(Micros(10), true), Micros(9), age));
    assert!(!is_fresh(
        Evidence::uncalculatable(Micros(10)),
        Micros(10),
        age
    ));
    assert!(!is_fresh(
        Evidence::new(Micros(i64::MIN), true),
        Micros(i64::MAX),
        age
    ));
}

#[test]
fn journal_commits_are_atomic_and_projection_is_incremental() {
    let mut journal = Journal::new();
    assert_eq!(journal.commit(vec![]), Err(JournalError::EmptyCommit));
    journal.commit(vec![obs(2, 1), obs(1, 1)]).unwrap();
    let mut projection = Projection::default();
    projection.update(&journal).unwrap();
    assert_eq!(projection.len(), 2);
    let old_cursor = projection.cursor();
    assert_eq!(
        journal.commit(vec![obs(3, 1)]),
        Err(JournalError::NonIncreasingCommit)
    );
    assert_eq!(
        journal.commit(vec![obs(3, 2), obs(4, 3)]),
        Err(JournalError::MixedCommit)
    );
    assert_eq!(
        journal.commit(vec![obs(3, 2), obs(3, 2)]),
        Err(JournalError::DuplicateRowId)
    );
    assert_eq!(
        journal.commit(vec![row(
            3,
            2,
            RowPayload::Recalculation {
                corrects: RowId(9),
                value: 4
            }
        )]),
        Err(JournalError::MissingObservation)
    );
    assert_eq!(journal.advance_cursor(old_cursor), old_cursor);
    journal
        .commit(vec![row(
            3,
            2,
            RowPayload::Recalculation {
                corrects: RowId(1),
                value: 42,
            },
        )])
        .unwrap();
    projection.update(&journal).unwrap();
    assert_eq!(projection.get(RowId(1)), Some(42));
    assert!(projection.cursor() > old_cursor);
    assert_eq!(journal.read_after(Cursor::start()).len(), 3);
    assert_eq!(
        journal.read_after(Cursor::start())[0].payload,
        RowPayload::Observation { value: 1 }
    );
}

#[test]
fn public_accessors_ordering_and_errors() {
    let ticker = Ticker::new(Asset::BTC, Currency::USDT);
    let price = Price::parse("2", ticker).unwrap();
    let quantity = Quantity::parse("2", Unit::Asset(Asset::BTC)).unwrap();
    let money = Money::parse("2", Currency::USDT).unwrap();
    assert_eq!(price.instrument(), ticker);
    assert_eq!(quantity.unit(), Unit::Asset(Asset::BTC));
    assert_eq!(money.currency(), Currency::USDT);
    assert_eq!(money.amount().to_string(), "2");
    assert!(price > Price::parse("1", ticker).unwrap());
    assert!(quantity > Quantity::parse("1", Unit::Asset(Asset::BTC)).unwrap());
    assert!(money > Money::parse("1", Currency::USDT).unwrap());
    assert_eq!(
        (money - Money::parse("1", Currency::USDT).unwrap()).unwrap(),
        Money::parse("1", Currency::USDT).unwrap()
    );
    assert!(!TypeParseError::Negative.to_string().is_empty());
    assert!(!ArithmeticError::Overflow.to_string().is_empty());
    assert!(!JournalError::EmptyCommit.to_string().is_empty());
    assert!(
        !calculus::types::ProjectionError::OutOfOrder
            .to_string()
            .is_empty()
    );
    assert_eq!(Micros::new(9).get(), 9);
    assert_eq!(Micros(9).to_string(), "9");
    assert_eq!(Cursor::start().to_string(), "0:0");
    let p = Projection::default();
    assert!(p.is_empty());
    assert_eq!(p.get(RowId(3)), None);
}
