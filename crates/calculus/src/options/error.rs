use std::fmt;

/// Invalid input or an unsupported numerical result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OptionsError {
    /// A numeric input is not finite or is outside its allowed range.
    InvalidInput,
    /// The calculation exceeds the supported floating-point range.
    Arithmetic,
}

impl fmt::Display for OptionsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for OptionsError {}
