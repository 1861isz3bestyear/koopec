//! Deterministic option calculations with caller-supplied Unix timestamps.
//! Open interest is contract count; multiplier is underlying units per contract.
mod error;
mod exposure;
mod flip;
mod levels;
mod max_pain;
mod model;

pub use error::OptionsError;
pub use exposure::{Exposure, exposure};
pub use flip::{FlipResult, FlipSearchConfig, FlipStatus, search_flips};
pub use levels::{
    ExposureSummary, ExposureTotals, RankedWalls, StrikeExposure, aggregate, ranked_walls,
};
pub use max_pain::{MaxPain, max_pain};
pub use model::{IdentifiedContract, OptionContract, OptionKind, OptionSnapshot, Valuation};
