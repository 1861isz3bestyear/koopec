use calculus::options::*;

fn contract(id: &str, side: OptionKind, strike: f64, expiry: i64, oi: f64) -> IdentifiedContract {
    IdentifiedContract::new(
        id.into(),
        OptionContract::new(side, strike, expiry, 0.5, oi, 1.0).unwrap(),
    )
    .unwrap()
}
fn snapshot(contracts: Vec<IdentifiedContract>) -> OptionSnapshot {
    OptionSnapshot::new(0, 1, Valuation::new(100.0, 1).unwrap(), contracts).unwrap()
}
const YEAR: i64 = 31_536_001;

#[test]
fn snapshot_rejects_unavailable_and_duplicate_data_and_preserves_provenance() {
    let c = contract("a", OptionKind::Call, 100.0, YEAR, 1.0);
    assert!(
        IdentifiedContract::new(
            "  ".into(),
            OptionContract::new(OptionKind::Call, 100.0, YEAR, 0.5, 1.0, 1.0).unwrap()
        )
        .is_err()
    );
    assert!(OptionSnapshot::new(1, 0, Valuation::new(100.0, 1).unwrap(), vec![]).is_err());
    assert!(OptionSnapshot::new(0, 2, Valuation::new(100.0, 1).unwrap(), vec![]).is_err());
    assert!(
        OptionSnapshot::new(
            0,
            1,
            Valuation::new(100.0, 1).unwrap(),
            vec![c.clone(), c.clone()]
        )
        .is_err()
    );
    let s = snapshot(vec![c]);
    assert!(s.revalue(Valuation::new(100.0, 0).unwrap()).is_err());
    let expired = s.revalue(Valuation::new(110.0, YEAR).unwrap()).unwrap();
    assert!(expired.is_empty());
    assert_eq!(expired.len(), 0);
    assert_eq!((expired.observed_at(), expired.available_at()), (0, 1));
}

#[test]
fn aggregate_cancellation_and_wall_ranges_are_independent() {
    let s = snapshot(vec![
        contract("put", OptionKind::Put, 100.0, YEAR, 10.0),
        contract("call", OptionKind::Call, 100.0, YEAR, 10.0),
    ]);
    let summary = aggregate(&s).unwrap();
    assert_eq!(summary.totals.signed, 0.0);
    assert!(summary.totals.absolute > 0.0);
    let walls = ranked_walls(&summary, 100.0, Some(0.2)).unwrap();
    assert_eq!(walls.calls.len(), 1);
    assert_eq!(walls.puts.len(), 1);
    let levels = ExposureSummary {
        strikes: vec![
            StrikeExposure {
                strike: 80.0,
                call: 2.0,
                put: -2.0,
            },
            StrikeExposure {
                strike: 120.0,
                call: 2.0,
                put: -2.0,
            },
            StrikeExposure {
                strike: 120.01,
                call: 3.0,
                put: -3.0,
            },
        ],
        totals: ExposureTotals {
            signed: 0.0,
            absolute: 0.0,
        },
    };
    let ranks = ranked_walls(&levels, 100.0, Some(0.2)).unwrap();
    assert_eq!(
        ranks.calls.iter().map(|x| x.strike).collect::<Vec<_>>(),
        vec![80.0, 120.0]
    );
    assert_eq!(ranks.puts[0].strike, 80.0);
    assert_eq!(
        ranked_walls(&levels, 100.0, None).unwrap().calls[0].strike,
        120.01
    );
    assert!(ranked_walls(&levels, 0.0, None).is_err());
    assert!(ranked_walls(&levels, 100.0, Some(1.0)).is_err());
}

#[test]
fn max_pain_handles_absence_ties_and_mixed_expiry() {
    assert_eq!(max_pain(&snapshot(vec![])).unwrap(), MaxPain::Empty);
    assert_eq!(
        max_pain(&snapshot(vec![contract(
            "a",
            OptionKind::Call,
            100.0,
            YEAR,
            0.0
        )]))
        .unwrap(),
        MaxPain::ZeroOpenInterest
    );
    let mixed = snapshot(vec![
        contract("a", OptionKind::Call, 100.0, YEAR, 1.0),
        contract("b", OptionKind::Put, 100.0, YEAR + 1, 1.0),
    ]);
    assert_eq!(max_pain(&mixed).unwrap(), MaxPain::MixedExpiry);
    let tied = snapshot(vec![
        contract("a", OptionKind::Call, 90.0, YEAR, 1.0),
        contract("b", OptionKind::Put, 110.0, YEAR, 1.0),
    ]);
    assert_eq!(max_pain(&tied).unwrap(), MaxPain::Strike(90.0));
}

#[test]
fn flip_search_detects_crossing_and_rejects_bad_settings() {
    for args in [
        (0.0, 120.0, 10, 0.001, 40),
        (80.0, 80.0, 10, 0.001, 40),
        (80.0, 120.0, 1, 0.001, 40),
        (80.0, 120.0, 10, 0.0, 40),
        (80.0, 120.0, 10, 0.001, 0),
    ] {
        assert!(FlipSearchConfig::new(args.0, args.1, args.2, args.3, args.4).is_err());
    }
    let config = FlipSearchConfig::new(50.0, 150.0, 20, 1e-8, 60).unwrap();
    let empty = search_flips(&snapshot(vec![]), config).unwrap();
    assert_eq!(empty.status, FlipStatus::ZeroPlateau);
    assert_eq!(empty.nearest(), None);
    let single = snapshot(vec![contract("a", OptionKind::Call, 100.0, YEAR, 1.0)]);
    assert_eq!(
        search_flips(&single, config).unwrap().status,
        FlipStatus::NoCrossing
    );
    let pair = snapshot(vec![
        contract("a", OptionKind::Call, 90.0, YEAR, 1.0),
        contract("b", OptionKind::Put, 110.0, YEAR, 1.0),
    ]);
    let result = search_flips(&pair, config).unwrap();
    assert_eq!(result.status, FlipStatus::Found);
    let root = result.nearest().unwrap();
    // Equal weights and volatility imply d1 values of opposite sign at this spot.
    let expected = (90.0_f64 * 110.0).sqrt() * (-0.125_f64).exp();
    assert!((root - expected).abs() < 1e-7);
    let limited = FlipSearchConfig::new(50.0, 150.0, 2, 1e-12, 1).unwrap();
    assert_eq!(
        search_flips(&pair, limited).unwrap().status,
        FlipStatus::Nonconverged
    );
}

#[test]
fn exposure_scales_with_open_interest_and_multiplier_and_expires_exactly() {
    let valuation = Valuation::new(100.0, 1).unwrap();
    let make = |oi, multiplier| {
        OptionContract::new(OptionKind::Call, 100.0, YEAR, 0.5, oi, multiplier).unwrap()
    };
    let Exposure::Live(base) = exposure(&make(1.0, 1.0), valuation).unwrap() else {
        panic!("expected live")
    };
    assert_eq!(
        exposure(&make(2.0, 1.0), valuation).unwrap(),
        Exposure::Live(base * 2.0)
    );
    assert_eq!(
        exposure(&make(1.0, 2.0), valuation).unwrap(),
        Exposure::Live(base * 2.0)
    );
    assert!(matches!(
        exposure(&make(1.0, 1.0), Valuation::new(100.0, YEAR - 1).unwrap()).unwrap(),
        Exposure::Live(_)
    ));
    assert_eq!(
        exposure(&make(1.0, 1.0), Valuation::new(100.0, YEAR + 1).unwrap()).unwrap(),
        Exposure::Expired
    );
    for value in [-1.0, f64::NAN, f64::INFINITY] {
        assert!(OptionContract::new(OptionKind::Put, 100.0, YEAR, 0.5, value, 1.0).is_err());
    }
    for value in [0.0, -1.0, f64::INFINITY, f64::NAN] {
        assert!(Valuation::new(value, 0).is_err());
    }
    let overflow = make(f64::MAX, 2.0);
    assert_eq!(
        exposure(&overflow, valuation),
        Err(OptionsError::Arithmetic)
    );
}

#[test]
fn aggregate_order_is_stable_even_for_near_cancellation() {
    let contracts = vec![
        contract("c", OptionKind::Call, 100.0, YEAR, 1.0),
        contract("a", OptionKind::Call, 100.0, YEAR, 1e15),
        contract("b", OptionKind::Put, 100.0, YEAR, 1e15),
    ];
    let mut reverse = contracts.clone();
    reverse.reverse();
    let first = aggregate(&snapshot(contracts)).unwrap();
    let second = aggregate(&snapshot(reverse)).unwrap();
    assert_eq!(first, second);
    assert!(first.totals.signed > 0.0);
    assert!(first.totals.absolute > first.totals.signed);
}

#[test]
fn revaluation_is_causal_and_removes_only_expired_contracts() {
    let s = snapshot(vec![
        contract("first", OptionKind::Call, 90.0, 10, 1.0),
        contract("second", OptionKind::Put, 110.0, 20, 1.0),
    ]);
    let at_ten = s.revalue(Valuation::new(110.0, 10).unwrap()).unwrap();
    assert_eq!(at_ten.len(), 1);
    assert_eq!(aggregate(&at_ten).unwrap().strikes[0].strike, 110.0);
    assert!(at_ten.revalue(Valuation::new(100.0, 9).unwrap()).is_err());
    assert_eq!(
        at_ten
            .revalue(Valuation::new(100.0, 20).unwrap())
            .unwrap()
            .len(),
        0
    );
    assert_eq!(s.len(), 2);
}

#[test]
fn two_flip_search_roots_are_ordered_and_residuals_change_sign() {
    let make = |id: &str, side, strike| {
        IdentifiedContract::new(
            id.into(),
            OptionContract::new(side, strike, YEAR, 0.2, 1.0, 1.0).unwrap(),
        )
        .unwrap()
    };
    let s = snapshot(vec![
        make("a", OptionKind::Call, 70.0),
        make("b", OptionKind::Put, 100.0),
        make("c", OptionKind::Call, 140.0),
    ]);
    let result = search_flips(
        &s,
        FlipSearchConfig::new(50.0, 170.0, 120, 1e-9, 60).unwrap(),
    )
    .unwrap();
    assert_eq!(result.status, FlipStatus::Found);
    assert_eq!(result.roots.len(), 2);
    assert!(result.roots[0] < 100.0 && result.roots[1] > 100.0);
    for root in result.roots {
        let left = aggregate(&s.revalue(Valuation::new(root - 1e-5, 1).unwrap()).unwrap())
            .unwrap()
            .totals
            .signed;
        let right = aggregate(&s.revalue(Valuation::new(root + 1e-5, 1).unwrap()).unwrap())
            .unwrap()
            .totals
            .signed;
        assert!(left * right < 0.0);
    }
}

#[test]
fn search_reports_grid_resolution_and_nearest_ties() {
    let s = snapshot(vec![contract("a", OptionKind::Call, 100.0, YEAR, 1.0)]);
    let upper = f64::from_bits(100.0_f64.to_bits() + 1);
    let result = search_flips(
        &s,
        FlipSearchConfig::new(100.0, upper, 2, f64::MIN_POSITIVE, 1).unwrap(),
    )
    .unwrap();
    assert_eq!(result.status, FlipStatus::InsufficientResolution);
    let result = FlipResult {
        config: FlipSearchConfig::new(1.0, 200.0, 2, 0.1, 2).unwrap(),
        status: FlipStatus::Found,
        roots: vec![110.0, 90.0],
        spot: 100.0,
    };
    assert_eq!(result.nearest(), Some(90.0));
}

#[test]
fn overflow_in_aggregation_and_max_pain_is_reported() {
    let a = contract("a", OptionKind::Call, 100.0, YEAR, f64::MAX);
    let b = contract("b", OptionKind::Call, 100.0, YEAR, f64::MAX);
    assert_eq!(
        aggregate(&snapshot(vec![a, b])),
        Err(OptionsError::Arithmetic)
    );
    let s = snapshot(vec![
        contract("a", OptionKind::Call, 1.0, YEAR, f64::MAX),
        contract("b", OptionKind::Put, 3.0, YEAR, f64::MAX),
    ]);
    assert_eq!(max_pain(&s), Err(OptionsError::Arithmetic));
}
