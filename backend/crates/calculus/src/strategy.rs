//! Quorum gate for already selected, fresh evidence.
use crate::accounts::Side;

/// Explicit result of the quorum and mandatory OI gate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GateResult {
    Allowed,
    InvalidQuorum,
    InsufficientVotes,
    MandatoryOiMissing,
}
/// Counts and OI evidence supplied after freshness and direction selection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EntryGate {
    pub required: usize,
    pub agreeing: usize,
    pub enabled_sources: usize,
    pub gex_enabled: bool,
    pub oi_enabled: bool,
    pub fresh_oi_side: Option<Side>,
}
impl EntryGate {
    /// Evaluate the gate; this is not a complete entry strategy.
    pub fn evaluate(self, side: Side) -> GateResult {
        if self.required == 0
            || self.required > self.enabled_sources
            || self.agreeing > self.enabled_sources
        {
            return GateResult::InvalidQuorum;
        }
        if self.agreeing < self.required {
            return GateResult::InsufficientVotes;
        }
        if self.gex_enabled && self.oi_enabled && self.fresh_oi_side != Some(side) {
            return GateResult::MandatoryOiMissing;
        }
        GateResult::Allowed
    }
}
