use calculus::accounts::{
    AccountError, EntryFill, ExitFill, HistoricalAccount, HistoricalAccountingRules, PositionState,
    Side,
};
use calculus::types::{Asset, Currency, Micros, Money, Price, Ticker};
use rust_decimal::Decimal;
use std::str::FromStr;
fn d(s: &str) -> Decimal {
    Decimal::from_str(s).unwrap()
}
fn price(s: &str) -> Price {
    Price::parse(s, Ticker::new(Asset::BTC, Currency::USDT)).unwrap()
}
fn rules() -> HistoricalAccountingRules {
    HistoricalAccountingRules::new(d("0.001")).unwrap()
}
fn account() -> HistoricalAccount {
    HistoricalAccount::new(Money::parse("1000", Currency::USDT).unwrap())
}
fn entry(side: Side) -> EntryFill {
    EntryFill {
        id: 1,
        side,
        price: price("100"),
        time: Micros(1),
    }
}
fn exit(s: &str, time: i64) -> ExitFill {
    ExitFill {
        id: 2,
        price: price(s),
        time: Micros(time),
    }
}
#[test]
fn long_mark_and_close_reproduce_book_example() {
    let mut a = account();
    let position = a.apply_entry(entry(Side::Long), &rules()).unwrap();
    assert_eq!(position.quantity, d("9.99"));
    assert_eq!(position.entry_fee, d("1"));
    assert_eq!(a.cash(), d("0"));
    assert_eq!(a.mark(price("110")).unwrap().equity, d("1098.9"));
    assert_eq!(a.mark(price("110")).unwrap().equity, d("1098.9"));
    let result = a.apply_exit(exit("110", 2), &rules()).unwrap();
    assert_eq!(result.cash, d("1097.8011"));
    assert_eq!(result.pnl, d("97.8011"));
    assert_eq!(result.fee, d("1.0989"));
    assert_eq!(a.position(), PositionState::Flat);
    assert_eq!(a.realized_pnl(), result.pnl);
    assert_eq!(a.mark(price("110")).unwrap().equity, result.cash);
}
#[test]
fn short_profit_loss_and_mark() {
    let mut a = account();
    a.apply_entry(entry(Side::Short), &rules()).unwrap();
    let mark = a.mark(price("90")).unwrap();
    assert_eq!(mark.equity, d("1098.9"));
    assert_eq!(mark.signed_quantity, d("-9.99"));
    let result = a.apply_exit(exit("90", 2), &rules()).unwrap();
    assert_eq!(result.cash, d("1098.0009"));
    assert_eq!(result.pnl, d("98.0009"));
    a.apply_entry(entry(Side::Short), &rules()).unwrap();
    assert!(a.apply_exit(exit("110", 2), &rules()).unwrap().pnl < Decimal::ZERO);
}
#[test]
fn invalid_transitions_leave_account_unchanged() {
    assert_eq!(
        HistoricalAccountingRules::new(d("-0.1")),
        Err(AccountError::InvalidFee)
    );
    assert_eq!(
        HistoricalAccountingRules::new(d("1")),
        Err(AccountError::InvalidFee)
    );
    let mut empty = HistoricalAccount::new(Money::parse("0", Currency::USDT).unwrap());
    assert_eq!(
        empty.apply_entry(entry(Side::Long), &rules()),
        Err(AccountError::EmptyBalance)
    );
    let mut a = account();
    assert_eq!(
        a.apply_exit(exit("90", 2), &rules()),
        Err(AccountError::NoPosition)
    );
    a.apply_entry(entry(Side::Short), &rules()).unwrap();
    let original = a.clone();
    assert_eq!(
        a.apply_entry(entry(Side::Long), &rules()),
        Err(AccountError::AlreadyOpen)
    );
    assert_eq!(
        a.apply_exit(exit("90", 0), &rules()),
        Err(AccountError::TimeOrder)
    );
    assert_eq!(
        a.apply_exit(exit("1000", 2), &rules()),
        Err(AccountError::NegativeCash)
    );
    assert_eq!(a, original);
}

#[test]
fn settlement_decision_table_covers_sides_prices_and_fee_boundaries() {
    // Independent values from the documented historical formula for a 1000 balance.
    for (side, closing, expected_cash, expected_pnl) in [
        (Side::Long, "90", "898.2009", "-101.7991"),
        (Side::Long, "100", "998.001", "-1.999"),
        (Side::Short, "110", "898.0011", "-101.9989"),
        (Side::Short, "100", "998.001", "-1.999"),
    ] {
        let mut a = account();
        a.apply_entry(entry(side), &rules()).unwrap();
        let result = a.apply_exit(exit(closing, 1), &rules()).unwrap();
        assert_eq!(result.cash, d(expected_cash), "{side:?}");
        assert_eq!(result.pnl, d(expected_pnl), "{side:?}");
    }
    let zero = HistoricalAccountingRules::new(Decimal::ZERO).unwrap();
    let mut a = account();
    a.apply_entry(entry(Side::Long), &zero).unwrap();
    assert_eq!(
        a.apply_exit(exit("100", 1), &zero).unwrap().pnl,
        Decimal::ZERO
    );
    assert!(HistoricalAccountingRules::new(d("0.9999999999999999999999999999")).is_ok());
}

#[test]
fn short_zero_cash_boundary_and_recovery() {
    let zero = HistoricalAccountingRules::new(Decimal::ZERO).unwrap();
    let mut a = account();
    a.apply_entry(entry(Side::Short), &zero).unwrap();
    let before = a.clone();
    assert_eq!(
        a.apply_exit(exit("200.00000001", 2), &zero),
        Err(AccountError::NegativeCash)
    );
    assert_eq!(a, before);
    assert_eq!(
        a.apply_exit(exit("200", 2), &zero).unwrap().cash,
        Decimal::ZERO
    );
    assert_eq!(a.realized_pnl(), d("-1000"));
}

#[test]
fn quantity_rounding_and_rejected_arithmetic_preserve_state() {
    let zero = HistoricalAccountingRules::new(Decimal::ZERO).unwrap();
    let mut a = HistoricalAccount::new(Money::parse("1", Currency::USDT).unwrap());
    let fill = EntryFill {
        price: price("3"),
        ..entry(Side::Long)
    };
    assert_eq!(
        a.apply_entry(fill, &zero).unwrap().quantity,
        d("0.3333333333333333")
    );
    let before = a.clone();
    // This product needs 32 fractional places and cannot be represented exactly.
    assert_eq!(
        a.apply_exit(
            exit("0.00000001", 2),
            &HistoricalAccountingRules::new(d("0.0000000000000000000000000001")).unwrap()
        ),
        Err(AccountError::Arithmetic)
    );
    assert_eq!(a, before);
    let mut tiny = HistoricalAccount::new(
        Money::parse("0.0000000000000000000000000001", Currency::USDT).unwrap(),
    );
    let unchanged = tiny.clone();
    assert_eq!(
        tiny.apply_entry(entry(Side::Long), &zero),
        Err(AccountError::Arithmetic)
    );
    assert_eq!(tiny, unchanged);
}

#[test]
fn successive_trades_accumulate_realized_profit_and_loss() {
    let mut a = account();
    a.apply_entry(entry(Side::Long), &rules()).unwrap();
    let first = a.apply_exit(exit("110", 2), &rules()).unwrap();
    a.apply_entry(
        EntryFill {
            time: Micros(3),
            ..entry(Side::Long)
        },
        &rules(),
    )
    .unwrap();
    let second = a.apply_exit(exit("90", 4), &rules()).unwrap();
    assert_eq!(a.realized_pnl(), first.pnl + second.pnl);
    assert_eq!(a.cash(), d("1000") + a.realized_pnl());
}
