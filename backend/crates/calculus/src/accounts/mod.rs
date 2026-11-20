//! Historical, fully allocated account model. Execution prices include slippage.
mod error;
mod events;
mod historical;
mod model;
pub use error::AccountError;
pub use events::{EntryFill, ExitFill, ExitSettlement, MarkedEquity};
pub use model::{HistoricalAccount, HistoricalAccountingRules, Position, PositionState, Side};
