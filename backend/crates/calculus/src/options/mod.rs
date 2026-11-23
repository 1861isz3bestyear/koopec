//! Deterministic option calculations with caller-supplied Unix timestamps.
//! Open interest is contract count; multiplier is underlying units per contract.
mod error;
mod history;
mod max_pain;
mod model;

pub use crate::gex::{
    Exposure, ExposureSummary, ExposureTotals, FlipResult, FlipSearchConfig, FlipStatus,
    RankedWalls, StrikeExposure, aggregate, exposure, ranked_walls, search_flips,
};
pub use error::OptionsError;
pub use history::{SavedSnapshot, SnapshotAsset, select_daily_snapshots, selected_snapshot_at};
pub use max_pain::{MaxPain, max_pain};
pub use model::{IdentifiedContract, OptionContract, OptionKind, OptionSnapshot, Valuation};
