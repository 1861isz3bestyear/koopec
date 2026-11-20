//! Exchange-independent order lifecycle primitives. No network or live trading.

/// Order intent status; an acknowledgement is not an execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderState {
    Prepared,
    SubmissionUnknown,
    Acknowledged,
    PartiallyFilled,
    Filled,
    Rejected,
}
/// Invalid event, repeated execution, or quantity arithmetic failure.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderError {
    InvalidTransition,
    DuplicateExecution,
    InvalidQuantity,
}
/// Tracked order using integer exchange quantity steps.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Order {
    id: String,
    quantity: u64,
    filled: u64,
    state: OrderState,
    executions: Vec<String>,
}
impl Order {
    /// Prepare an intent; the caller must durably commit it before submission.
    pub fn new(id: String, quantity: u64) -> Result<Self, OrderError> {
        if id.trim().is_empty() || quantity == 0 {
            return Err(OrderError::InvalidQuantity);
        }
        Ok(Self {
            id,
            quantity,
            filled: 0,
            state: OrderState::Prepared,
            executions: Vec::new(),
        })
    }
    pub fn state(&self) -> OrderState {
        self.state
    }
    pub fn filled(&self) -> u64 {
        self.filled
    }
    /// A transport timeout requires reconciliation before retrying submission.
    pub fn submission_unknown(&mut self) -> Result<(), OrderError> {
        if self.state != OrderState::Prepared {
            return Err(OrderError::InvalidTransition);
        }
        self.state = OrderState::SubmissionUnknown;
        Ok(())
    }
    /// Record an exchange acknowledgement; no quantity is filled by this event.
    pub fn acknowledge(&mut self) -> Result<(), OrderError> {
        if !matches!(
            self.state,
            OrderState::Prepared | OrderState::SubmissionUnknown
        ) {
            return Err(OrderError::InvalidTransition);
        }
        self.state = OrderState::Acknowledged;
        Ok(())
    }
    /// Record explicit rejection before any fill.
    pub fn reject(&mut self) -> Result<(), OrderError> {
        if !matches!(
            self.state,
            OrderState::Prepared | OrderState::SubmissionUnknown | OrderState::Acknowledged
        ) {
            return Err(OrderError::InvalidTransition);
        }
        self.state = OrderState::Rejected;
        Ok(())
    }
    /// Apply a unique exchange execution atomically, including when REST timed out.
    pub fn execution(&mut self, execution_id: String, quantity: u64) -> Result<(), OrderError> {
        if self.executions.contains(&execution_id) {
            return Err(OrderError::DuplicateExecution);
        }
        if !matches!(
            self.state,
            OrderState::SubmissionUnknown | OrderState::Acknowledged | OrderState::PartiallyFilled
        ) {
            return Err(OrderError::InvalidTransition);
        }
        let total = self
            .filled
            .checked_add(quantity)
            .ok_or(OrderError::InvalidQuantity)?;
        if execution_id.trim().is_empty() || quantity == 0 || total > self.quantity {
            return Err(OrderError::InvalidQuantity);
        }
        self.executions.push(execution_id);
        self.filled = total;
        self.state = if total == self.quantity {
            OrderState::Filled
        } else {
            OrderState::PartiallyFilled
        };
        Ok(())
    }
}
