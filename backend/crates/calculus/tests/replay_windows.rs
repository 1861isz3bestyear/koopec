use calculus::indicators::{IndicatorState, InterestObservation, Interval, OiMomentum};
use calculus::options::select_daily_receipts;
use calculus::plans::{PlanWindow, active_plan_indices};

#[test]
fn daily_selection_preserves_fractional_distance_and_earlier_ties() {
    let target = 29_700_000_000;
    assert_eq!(
        select_daily_receipts([(0, target + 2), (1, target - 1)].into_iter()),
        [1]
    );
    assert_eq!(
        select_daily_receipts([(0, target + 1), (1, target - 1), (2, target - 1)].into_iter()),
        [1]
    );
}

#[test]
fn replay_uses_inclusive_receipts_exclusive_expiry_and_latest_plan() {
    let plans = [
        PlanWindow {
            available: 10,
            expires: 20,
        },
        PlanWindow {
            available: 15,
            expires: 17,
        },
        PlanWindow {
            available: 21,
            expires: 25,
        },
    ];
    assert_eq!(
        active_plan_indices(&plans, &[9, 10, 14, 15, 16, 17, 19, 20, 21, 24, 25]).unwrap(),
        [
            None,
            Some(0),
            Some(0),
            Some(1),
            Some(1),
            None,
            None,
            None,
            Some(2),
            Some(2),
            None
        ]
    );
    assert!(active_plan_indices(&[plans[1], plans[0]], &[15]).is_err());
}

#[test]
fn oi_momentum_resets_on_a_one_microsecond_gap() {
    let mut indicator = OiMomentum::with_microseconds(Interval::Hourly);
    let hour = 3_600_000_000;
    for index in 0..15 {
        let time = index * hour + 1;
        let oi = if index < 12 { 100.0 } else { 125.0 };
        let state = indicator
            .update(InterestObservation::new(time, time, oi, 10.0).unwrap())
            .unwrap();
        if index == 14 {
            assert!(
                matches!(state, IndicatorState::Ready { value, .. } if (value - 25.0).abs() < 1e-12)
            );
        } else {
            assert!(matches!(state, IndicatorState::WarmingUp { .. }));
        }
    }
    assert!(matches!(
        indicator
            .update(InterestObservation::new(15 * hour + 2, 15 * hour + 2, 125.0, 10.0).unwrap())
            .unwrap(),
        IndicatorState::Gap { .. }
    ));
}
