//! Deterministic historical execution. Entry-bar targets are not filled.
mod simulator;
pub use simulator::{
    CandleCompleted, CandleOpened, EntryDecision, ExecutionError, ExecutionEvent, ExecutionPolicy,
    ExitReason, Protection, Simulator,
};

mod tunnel;
pub use tunnel::{TunnelBar, TunnelMark, TunnelRisk, TunnelRun, TunnelTrade, simulate_tunnel};
