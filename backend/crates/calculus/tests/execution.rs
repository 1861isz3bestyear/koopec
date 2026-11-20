use calculus::accounts::{HistoricalAccount, HistoricalAccountingRules, PositionState, Side};
use calculus::execution::{
    CandleCompleted, CandleOpened, EntryDecision, ExecutionError, ExecutionEvent, ExecutionPolicy,
    ExitReason, Protection, Simulator,
};
use calculus::types::{Asset, Currency, Micros, Money, Price, Ticker};
use rust_decimal::Decimal;
use std::str::FromStr;
fn d(s: &str) -> Decimal {
    Decimal::from_str(s).unwrap()
}
fn p(s: &str) -> Price {
    Price::parse(s, Ticker::new(Asset::BTC, Currency::USDT)).unwrap()
}
fn candle(time: i64, open: &str) -> CandleOpened {
    CandleOpened {
        time: Micros(time),
        open: p(open),
    }
}
fn complete(c: CandleOpened, high: &str, low: &str, close: &str) -> CandleCompleted {
    CandleCompleted::new(c, p(high), p(low), p(close)).unwrap()
}
fn setup(
    side: Side,
    bps: &str,
) -> (
    Simulator,
    HistoricalAccount,
    HistoricalAccountingRules,
    EntryDecision,
) {
    let decision = EntryDecision {
        side,
        price: p("100"),
        protection: match side {
            Side::Long => Protection::new(side, p("100"), p("98"), p("105")).unwrap(),
            Side::Short => Protection::new(side, p("100"), p("102"), p("95")).unwrap(),
        },
    };
    (
        Simulator::new(ExecutionPolicy::new(d(bps)).unwrap()),
        HistoricalAccount::new(Money::parse("1000", Currency::USDT).unwrap()),
        HistoricalAccountingRules::new(d("0.001")).unwrap(),
        decision,
    )
}
fn enter(
    sim: &mut Simulator,
    account: &mut HistoricalAccount,
    rules: &HistoricalAccountingRules,
    decision: EntryDecision,
) {
    let c = candle(1, "100");
    assert!(matches!(
        sim.on_open(account, c, Some(decision), 1, rules).unwrap(),
        Some(ExecutionEvent::Entry(_))
    ));
    assert_eq!(
        sim.on_complete(account, complete(c, "100", "100", "100"), 2, rules)
            .unwrap(),
        None
    );
}
#[test]
fn opening_target_precedes_later_stop_and_prevents_reentry() {
    let (mut sim, mut a, rules, decision) = setup(Side::Long, "0");
    enter(&mut sim, &mut a, &rules, decision);
    let c = candle(2, "106");
    let event = sim
        .on_open(&mut a, c, Some(decision), 3, &rules)
        .unwrap()
        .unwrap();
    assert!(
        matches!(event, ExecutionEvent::Exit { fill, reason: ExitReason::TakeProfit } if fill.price == p("105"))
    );
    assert_eq!(
        sim.on_complete(&mut a, complete(c, "107", "97", "100"), 4, &rules)
            .unwrap(),
        None
    );
    assert_eq!(a.position(), PositionState::Flat);
}
#[test]
fn intrabar_stop_wins_and_short_gap_uses_open() {
    for side in [Side::Long, Side::Short] {
        let (mut sim, mut a, rules, decision) = setup(side, "0");
        enter(&mut sim, &mut a, &rules, decision);
        let c = candle(2, "100");
        sim.on_open(&mut a, c, None, 3, &rules).unwrap();
        let event = sim
            .on_complete(&mut a, complete(c, "106", "94", "100"), 4, &rules)
            .unwrap()
            .unwrap();
        let expected = if side == Side::Long {
            p("98")
        } else {
            p("102")
        };
        assert!(
            matches!(event, ExecutionEvent::Exit { fill, reason: ExitReason::StopLoss } if fill.price == expected)
        );
    }
    let (mut sim, mut a, rules, decision) = setup(Side::Short, "0");
    enter(&mut sim, &mut a, &rules, decision);
    let result = sim
        .on_open(&mut a, candle(2, "103"), None, 3, &rules)
        .unwrap()
        .unwrap();
    assert!(
        matches!(result, ExecutionEvent::Exit { fill, reason: ExitReason::StopLoss } if fill.price == p("103"))
    );
}
#[test]
fn entry_bar_profit_is_ignored_but_stop_is_executed() {
    let (mut sim, mut a, rules, decision) = setup(Side::Long, "0");
    let c = candle(1, "100");
    sim.on_open(&mut a, c, Some(decision), 1, &rules).unwrap();
    assert_eq!(
        sim.on_complete(&mut a, complete(c, "106", "99", "100"), 2, &rules)
            .unwrap(),
        None
    );
    let (mut sim, mut a, rules, decision) = setup(Side::Long, "0");
    sim.on_open(&mut a, c, Some(decision), 1, &rules).unwrap();
    assert!(matches!(
        sim.on_complete(&mut a, complete(c, "106", "97", "100"), 2, &rules)
            .unwrap(),
        Some(ExecutionEvent::Exit {
            reason: ExitReason::StopLoss,
            ..
        })
    ));
}
#[test]
fn slippage_is_applied_once_in_both_directions() {
    for (side, entry_price, exit_price) in [
        (Side::Long, "100.1", "97.902"),
        (Side::Short, "99.9", "102.102"),
    ] {
        let (mut sim, mut a, rules, decision) = setup(side, "10");
        let c = candle(1, "100");
        assert!(
            matches!(sim.on_open(&mut a, c, Some(decision), 1, &rules).unwrap(), Some(ExecutionEvent::Entry(fill)) if fill.price == p(entry_price))
        );
        assert!(
            matches!(sim.on_complete(&mut a, complete(c, "103", "97", "100"), 2, &rules).unwrap(), Some(ExecutionEvent::Exit { fill, reason: ExitReason::StopLoss }) if fill.price == p(exit_price))
        );
    }
}
#[test]
fn invalid_data_and_event_order_do_not_mutate_state() {
    assert_eq!(
        ExecutionPolicy::new(d("-1")),
        Err(ExecutionError::InvalidSlippage)
    );
    assert_eq!(
        ExecutionPolicy::new(d("10000")),
        Err(ExecutionError::InvalidSlippage)
    );
    assert_eq!(
        Protection::new(Side::Long, p("100"), p("101"), p("105")),
        Err(ExecutionError::InvalidProtection)
    );
    let c = candle(1, "100");
    assert_eq!(
        CandleCompleted::new(c, p("99"), p("98"), p("99")),
        Err(ExecutionError::InvalidCandle)
    );
    let (mut sim, mut a, rules, decision) = setup(Side::Long, "0");
    let snapshot = sim.clone();
    let old = a.clone();
    assert_eq!(
        sim.on_complete(&mut a, complete(c, "100", "100", "100"), 1, &rules),
        Err(ExecutionError::Chronology)
    );
    assert_eq!(sim, snapshot);
    assert_eq!(a, old);
    sim.on_open(&mut a, c, Some(decision), 1, &rules).unwrap();
    let snapshot = sim.clone();
    let old = a.clone();
    assert_eq!(
        sim.on_open(&mut a, c, None, 2, &rules),
        Err(ExecutionError::Chronology)
    );
    assert_eq!(
        sim.on_complete(
            &mut a,
            complete(candle(2, "100"), "100", "100", "100"),
            2,
            &rules
        ),
        Err(ExecutionError::Chronology)
    );
    assert_eq!(sim, snapshot);
    assert_eq!(a, old);
}

#[test]
fn rejected_settlement_keeps_simulator_and_account_unchanged() {
    let (mut sim, mut account, rules, decision) = setup(Side::Short, "0");
    enter(&mut sim, &mut account, &rules, decision);
    let previous_sim = sim.clone();
    let previous_account = account.clone();
    assert_eq!(
        sim.on_open(&mut account, candle(2, "1000"), None, 3, &rules),
        Err(ExecutionError::Account(
            calculus::accounts::AccountError::NegativeCash
        ))
    );
    assert_eq!(sim, previous_sim);
    assert_eq!(account, previous_account);
    assert!(matches!(
        sim.on_open(&mut account, candle(2, "103"), None, 3, &rules)
            .unwrap(),
        Some(ExecutionEvent::Exit {
            reason: ExitReason::StopLoss,
            ..
        })
    ));
}
