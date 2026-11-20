use server_bot::{Order, OrderError, OrderState};

#[test]
fn timeout_followed_by_partial_and_complete_execution_never_assumes_a_fill() {
    let mut order = Order::new("run-1".into(), 10).unwrap();
    order.submission_unknown().unwrap();
    assert_eq!(
        (order.state(), order.filled()),
        (OrderState::SubmissionUnknown, 0)
    );
    order.execution("fill-1".into(), 4).unwrap();
    assert_eq!(
        (order.state(), order.filled()),
        (OrderState::PartiallyFilled, 4)
    );
    let before = order.clone();
    assert_eq!(
        order.execution("fill-1".into(), 4),
        Err(OrderError::DuplicateExecution)
    );
    assert_eq!(order, before);
    assert_eq!(
        order.execution("fill-2".into(), 7),
        Err(OrderError::InvalidQuantity)
    );
    assert_eq!(order, before);
    order.execution("fill-2".into(), 6).unwrap();
    assert_eq!((order.state(), order.filled()), (OrderState::Filled, 10));
    assert_eq!(order.reject(), Err(OrderError::InvalidTransition));
}

#[test]
fn acknowledgment_rejection_and_invalid_transitions() {
    assert!(Order::new(" ".into(), 1).is_err());
    assert!(Order::new("a".into(), 0).is_err());
    let mut order = Order::new("a".into(), 1).unwrap();
    let before = order.clone();
    assert_eq!(
        order.execution("x".into(), 1),
        Err(OrderError::InvalidTransition)
    );
    assert_eq!(order, before);
    order.acknowledge().unwrap();
    assert_eq!(
        (order.state(), order.filled()),
        (OrderState::Acknowledged, 0)
    );
    for (id, qty) in [("", 1), ("x", 0), ("x", 2)] {
        assert_eq!(
            order.execution(id.into(), qty),
            Err(OrderError::InvalidQuantity)
        );
    }
    order.reject().unwrap();
    assert_eq!(order.state(), OrderState::Rejected);
    assert_eq!(order.acknowledge(), Err(OrderError::InvalidTransition));
    assert_eq!(
        order.submission_unknown(),
        Err(OrderError::InvalidTransition)
    );
}
