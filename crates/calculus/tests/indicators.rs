use calculus::indicators::*;

fn level(price: f64, quantity: f64) -> BookLevel {
    BookLevel::new(price, quantity).unwrap()
}
fn growth(i: i64, value: f64) -> GrowthObservation {
    GrowthObservation::new(i * 3600, i * 3600, value).unwrap()
}
fn interest(i: i64, step: i64, value: f64) -> InterestObservation {
    InterestObservation::new(i * step, i * step, value, 100.0).unwrap()
}

#[test]
fn book_notional_boundaries_and_invalid_inputs() {
    assert_eq!(
        book_rate(&[level(100.0, 6.0)], &[level(100.0, 4.0)]),
        Ok(Some(60.0))
    );
    assert_eq!(
        book_rate(&[level(1.0, 1.0)], &[level(1.0, 1.0)]),
        Ok(Some(50.0))
    );
    assert_eq!(book_rate(&[level(1.0, 1.0)], &[]), Ok(Some(100.0)));
    assert_eq!(book_rate(&[], &[level(1.0, 1.0)]), Ok(Some(0.0)));
    assert_eq!(book_rate(&[level(1.0, 0.0)], &[]), Ok(None));
    for bad in [0.0, -1.0, f64::NAN, f64::INFINITY] {
        assert!(BookLevel::new(bad, 1.0).is_err());
    }
    for bad in [-1.0, f64::NAN, f64::INFINITY] {
        assert!(BookLevel::new(1.0, bad).is_err());
    }
    assert_eq!(
        book_rate(&[level(f64::MAX, 2.0)], &[]),
        Err(IndicatorError::Arithmetic)
    );
    assert_eq!(
        book_rate(&[level(f64::MAX, 1.0)], &[level(f64::MAX, 1.0)]),
        Err(IndicatorError::Arithmetic)
    );
}

#[test]
fn margin_warmup_values_slide_and_gap_recovery() {
    for (growth_value, expected) in [(1.0, 100.0), (-1.0, 0.0), (0.0, 50.0)] {
        let mut state = MarginMomentum::new();
        for i in 0..13 {
            assert_eq!(
                state.update(growth(i, growth_value)).unwrap(),
                IndicatorState::WarmingUp {
                    observed: i as usize + 1,
                    required: 14
                }
            );
        }
        assert!(
            matches!(state.update(growth(13, growth_value)), Ok(IndicatorState::Ready { value, .. }) if value == expected)
        );
    }
    let mut state = MarginMomentum::new();
    for i in 0..14 {
        let v = if i < 7 { 2.0 } else { -1.0 };
        let result = state.update(growth(i, v)).unwrap();
        if i == 13 {
            assert!(
                matches!(result, IndicatorState::Ready { value, .. } if (value-200.0/3.0).abs() < 1e-12)
            );
        }
    }
    assert!(
        matches!(state.update(growth(14,-1.0)), Ok(IndicatorState::Ready { value, .. }) if (value-60.0).abs() < 1e-12)
    );
    assert_eq!(
        state.update(growth(16, 1.0)),
        Ok(IndicatorState::Gap {
            observed: 1,
            required: 14
        })
    );
    for i in 17..29 {
        assert!(matches!(
            state.update(growth(i, 1.0)),
            Ok(IndicatorState::WarmingUp { .. })
        ));
    }
    assert!(matches!(
        state.update(growth(29, 1.0)),
        Ok(IndicatorState::Ready { value: 100.0, .. })
    ));
}

#[test]
fn margin_receipt_and_rejected_update_are_causal_and_atomic() {
    assert!(GrowthObservation::new(1, 0, 0.0).is_err());
    assert!(GrowthObservation::new(0, 0, f64::NAN).is_err());
    let mut state = MarginMomentum::new();
    for i in 0..13 {
        let time = i * 3600;
        let received = if i == 0 { 100_000 } else { time };
        state
            .update(GrowthObservation::new(time, received, 1.0).unwrap())
            .unwrap();
    }
    let ready = state.update(growth(13, 1.0)).unwrap();
    assert!(matches!(
        ready,
        IndicatorState::Ready {
            available_at: 100_000,
            ..
        }
    ));
    let before = state.clone();
    assert_eq!(
        state.update(growth(13, 1.0)),
        Err(IndicatorError::OutOfOrder)
    );
    assert_eq!(state, before);
    assert!(matches!(
        state.update(growth(14, 1.0)),
        Ok(IndicatorState::Ready {
            available_at: 50_400,
            ..
        })
    ));
}

#[test]
fn oi_warmup_is_147_five_minute_and_15_hourly_samples() {
    for (interval, step, required) in [
        (Interval::FiveMinutes, 300, 147),
        (Interval::Hourly, 3600, 15),
    ] {
        let mut state = OiMomentum::new(interval);
        for i in 0..required {
            let result = state.update(interest(i, step, 100.0)).unwrap();
            if i < required - 1 {
                assert_eq!(
                    result,
                    IndicatorState::WarmingUp {
                        observed: i as usize + 1,
                        required: required as usize
                    }
                );
            } else {
                assert!(matches!(result, IndicatorState::Ready { value: 0.0, .. }));
            }
        }
        assert_eq!(
            state.update(interest(required + 1, step, 100.0)),
            Ok(IndicatorState::Gap {
                observed: 1,
                required: required as usize
            })
        );
    }
}

#[test]
fn oi_known_growth_late_receipt_and_failure_do_not_mutate() {
    let mut state = OiMomentum::new(Interval::Hourly);
    for i in 0..15 {
        let t = i * 3600;
        let oi = if i < 12 { 100.0 } else { 110.0 };
        let receipt = if i == 0 { 99_999 } else { t };
        let result = state
            .update(InterestObservation::new(t, receipt, oi, 100.0).unwrap())
            .unwrap();
        if i == 14 {
            assert!(
                matches!(result, IndicatorState::Ready { value, available_at: 99_999, .. } if (value-10.0).abs() < 1e-12)
            );
        }
    }
    let before = state.clone();
    assert_eq!(
        state.update(interest(14, 3600, 1.0)),
        Err(IndicatorError::OutOfOrder)
    );
    assert_eq!(state, before);
    for bad in [0.0, -1.0, f64::NAN, f64::INFINITY] {
        assert!(InterestObservation::new(0, 0, bad, 1.0).is_err());
        assert!(InterestObservation::new(0, 0, 1.0, bad).is_err());
    }
    assert!(InterestObservation::new(1, 0, 1.0, 1.0).is_err());
    let mut overflow = OiMomentum::new(Interval::Hourly);
    for i in 0..14 {
        overflow
            .update(interest(i, 3600, f64::MIN_POSITIVE))
            .unwrap();
    }
    let before = overflow.clone();
    assert_eq!(
        overflow.update(interest(14, 3600, f64::MAX)),
        Err(IndicatorError::Arithmetic)
    );
    assert_eq!(overflow, before);
}

#[test]
fn pivot_detection_requires_strict_prominent_swing_and_causal_receipts() {
    let points = [
        PivotPoint::new(0, 0, 90.0, 90.0, 1.0).unwrap(),
        PivotPoint::new(1, 1, 95.0, 95.0, 2.0).unwrap(),
        PivotPoint::new(2, 2, 100.0, 100.0, 3.0).unwrap(),
        PivotPoint::new(3, 20, 95.0, 95.0, 2.0).unwrap(),
        PivotPoint::new(4, 4, 90.0, 90.0, 1.0).unwrap(),
    ];
    let pivot = detect_pivot(&points, Comparison::OpenInterest, 10.0)
        .unwrap()
        .unwrap();
    assert_eq!(
        (pivot.kind, pivot.pivot_at, pivot.available_at, pivot.value),
        (PivotKind::High, 2, 20, 100.0)
    );
    assert_eq!(
        detect_pivot(&points, Comparison::Momentum, 10.001).unwrap(),
        None
    );
    let mut plateau = points;
    plateau[3] = PivotPoint::new(3, 3, 100.0, 95.0, 2.0).unwrap();
    assert_eq!(
        detect_pivot(&plateau, Comparison::Momentum, 0.0).unwrap(),
        None
    );
    let mut flat_oi = points;
    flat_oi[3] = PivotPoint::new(3, 3, 95.0, 100.0, 2.0).unwrap();
    assert_eq!(
        detect_pivot(&flat_oi, Comparison::OpenInterest, 0.0).unwrap(),
        None
    );
    assert!(detect_pivot(&points, Comparison::Momentum, f64::NAN).is_err());
    assert!(PivotPoint::new(1, 0, 1.0, 1.0, 0.0).is_err());
    assert!(PivotPoint::new(0, 0, 0.0, 1.0, 0.0).is_err());
}

#[test]
fn swing_comparison_table_covers_direction_and_thresholds() {
    let pivot = |kind, time, price, value| Pivot {
        kind,
        pivot_at: time,
        available_at: time,
        price,
        value,
    };
    for (kind, old_price, new_price, old_value, new_value, expected) in [
        (
            PivotKind::High,
            100.0,
            110.0,
            1.0,
            2.0,
            SwingRelation::Agreement,
        ),
        (
            PivotKind::High,
            100.0,
            110.0,
            2.0,
            1.0,
            SwingRelation::Divergence,
        ),
        (
            PivotKind::Low,
            100.0,
            90.0,
            2.0,
            1.0,
            SwingRelation::Agreement,
        ),
        (
            PivotKind::Low,
            100.0,
            90.0,
            1.0,
            2.0,
            SwingRelation::Divergence,
        ),
    ] {
        let a = pivot(kind, 0, old_price, old_value);
        let b = pivot(kind, 1, new_price, new_value);
        assert_eq!(
            compare_pivots(a, b, Comparison::Momentum, 9.0, 1.0),
            Ok(Some(expected))
        );
        assert_eq!(
            compare_pivots(a, b, Comparison::Momentum, 11.0, 0.0),
            Ok(None)
        );
        assert_eq!(
            compare_pivots(a, b, Comparison::Momentum, 0.0, 1.01),
            Ok(None)
        );
        assert_eq!(
            compare_pivots(a, a, Comparison::Momentum, 0.0, 0.0),
            Err(IndicatorError::InvalidInput)
        );
    }
    let a = pivot(PivotKind::High, 0, 100.0, 100.0);
    let b = pivot(PivotKind::High, 1, 110.0, 90.0);
    assert_eq!(
        compare_pivots(a, b, Comparison::OpenInterest, 0.0, 9.0),
        Ok(Some(SwingRelation::Divergence))
    );
    assert_eq!(
        compare_pivots(
            a,
            pivot(PivotKind::High, 1, 99.0, 90.0),
            Comparison::Momentum,
            0.0,
            0.0
        ),
        Ok(None)
    );
}

#[test]
fn margin_restart_at_each_prefix_preserves_future_results_and_gap_recovery() {
    let points: Vec<_> = (0..35)
        .map(|i| {
            let hour = if i < 16 { i } else { i + 1 };
            growth(hour, if i % 3 == 0 { -2.0 } else { 1.0 })
        })
        .collect();
    let mut original = MarginMomentum::new();
    let expected: Vec<_> = points
        .iter()
        .map(|p| original.update(*p).unwrap())
        .collect();
    for split in 0..=points.len() {
        let mut before_restart = MarginMomentum::new();
        for (index, point) in points[..split].iter().enumerate() {
            assert_eq!(before_restart.update(*point).unwrap(), expected[index]);
        }
        let mut restored = before_restart.clone();
        for (index, point) in points[split..].iter().enumerate() {
            assert_eq!(restored.update(*point).unwrap(), expected[split + index]);
        }
        assert_eq!(restored, original);
    }
}

#[test]
fn oi_restart_at_each_prefix_preserves_observations_and_gap_recovery() {
    let points: Vec<_> = (0..36)
        .map(|i| {
            let hour = if i < 18 { i } else { i + 1 };
            interest(hour, 3600, 100.0 + i as f64)
        })
        .collect();
    let mut original = OiMomentum::new(Interval::Hourly);
    let expected: Vec<_> = points
        .iter()
        .map(|p| original.update(*p).unwrap())
        .collect();
    for split in 0..=points.len() {
        let mut prefix = OiMomentum::new(Interval::Hourly);
        for (index, point) in points[..split].iter().enumerate() {
            assert_eq!(prefix.update(*point).unwrap(), expected[index]);
        }
        let mut restored = prefix.clone();
        for (index, point) in points[split..].iter().enumerate() {
            assert_eq!(restored.update(*point).unwrap(), expected[split + index]);
        }
        assert_eq!(restored, original);
    }
}

#[test]
fn irregular_intervals_and_time_reversal_do_not_act_like_valid_contiguous_samples() {
    let mut margin = MarginMomentum::new();
    margin
        .update(GrowthObservation::new(3600, 3600, 1.0).unwrap())
        .unwrap();
    let before = margin.clone();
    assert_eq!(
        margin.update(GrowthObservation::new(3599, 3599, 1.0).unwrap()),
        Err(IndicatorError::OutOfOrder)
    );
    assert_eq!(margin, before);
    assert_eq!(
        margin.update(GrowthObservation::new(7199, 7199, 1.0).unwrap()),
        Ok(IndicatorState::Gap {
            observed: 1,
            required: 14
        })
    );
    let mut oi = OiMomentum::new(Interval::FiveMinutes);
    oi.update(interest(0, 300, 100.0)).unwrap();
    assert_eq!(
        oi.update(InterestObservation::new(301, 301, 100.0, 100.0).unwrap()),
        Ok(IndicatorState::Gap {
            observed: 1,
            required: 147
        })
    );
}
