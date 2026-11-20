use calculus::{
    accounts::Side,
    metrics::{ReturnError, net_return},
    plans::{PositiveTunnel, TunnelState},
    strategy::{EntryGate, GateResult},
};
use rust_decimal::Decimal;
use rust_decimal::prelude::FromPrimitive;

#[test]
fn tunnel_classification_has_explicit_precedence_and_inclusive_boundaries() {
    let t = PositiveTunnel::new(100.0, 120.0, 100.0).unwrap();
    assert_eq!(t.classify(0.2), Ok(TunnelState::Tight));
    assert_eq!(t.classify(0.19), Ok(TunnelState::FlipInside));
    assert_eq!(
        PositiveTunnel::new(100.0, 120.0, 99.0)
            .unwrap()
            .classify(0.19),
        Ok(TunnelState::FlipBelow)
    );
    for (l, u, f) in [
        (0.0, 1.0, 0.5),
        (2.0, 1.0, 0.5),
        (1.0, 2.0, 2.0),
        (f64::NAN, 2.0, 1.0),
    ] {
        assert!(PositiveTunnel::new(l, u, f).is_err());
    }
    assert!(t.classify(-1.0).is_err());
    assert!(t.classify(f64::INFINITY).is_err());
    assert!(
        PositiveTunnel::new(f64::MIN_POSITIVE, f64::MAX, 1.0)
            .unwrap()
            .classify(0.0)
            .is_err()
    );
}

#[test]
fn quorum_decision_table_requires_oi_only_when_both_enabled() {
    for gex in [false, true] {
        for oi in [false, true] {
            for evidence in [None, Some(Side::Long), Some(Side::Short)] {
                let gate = EntryGate {
                    required: 2,
                    agreeing: 2,
                    enabled_sources: 3,
                    gex_enabled: gex,
                    oi_enabled: oi,
                    fresh_oi_side: evidence,
                };
                let expected = if gex && oi && evidence != Some(Side::Long) {
                    GateResult::MandatoryOiMissing
                } else {
                    GateResult::Allowed
                };
                assert_eq!(gate.evaluate(Side::Long), expected);
            }
        }
    }
    let base = EntryGate {
        required: 2,
        agreeing: 1,
        enabled_sources: 3,
        gex_enabled: true,
        oi_enabled: true,
        fresh_oi_side: None,
    };
    assert_eq!(base.evaluate(Side::Long), GateResult::InsufficientVotes);
    assert_eq!(
        EntryGate {
            required: 0,
            ..base
        }
        .evaluate(Side::Long),
        GateResult::InvalidQuorum
    );
    assert_eq!(
        EntryGate {
            required: 4,
            ..base
        }
        .evaluate(Side::Long),
        GateResult::InvalidQuorum
    );
    assert_eq!(
        EntryGate {
            agreeing: 4,
            ..base
        }
        .evaluate(Side::Long),
        GateResult::InvalidQuorum
    );
    assert_eq!(
        EntryGate {
            agreeing: 2,
            fresh_oi_side: Some(Side::Short),
            ..base
        }
        .evaluate(Side::Short),
        GateResult::Allowed
    );
}

#[test]
fn net_return_distinguishes_profit_loss_and_invalid_capital() {
    let initial = Decimal::from(1000);
    assert_eq!(
        net_return(initial, Decimal::from(1100)),
        Ok(Decimal::from_f64(0.1).unwrap())
    );
    assert_eq!(
        net_return(initial, Decimal::from(900)),
        Ok(Decimal::from_f64(-0.1).unwrap())
    );
    assert_eq!(net_return(initial, initial), Ok(Decimal::ZERO));
    assert_eq!(
        net_return(initial, Decimal::ZERO),
        Ok(Decimal::NEGATIVE_ONE)
    );
    assert_eq!(
        net_return(Decimal::ZERO, initial),
        Err(ReturnError::InvalidCapital)
    );
    assert_eq!(
        net_return(initial, Decimal::NEGATIVE_ONE),
        Err(ReturnError::InvalidCapital)
    );
    assert_eq!(
        net_return(Decimal::new(1, 28), Decimal::MAX),
        Err(ReturnError::Arithmetic)
    );
}
