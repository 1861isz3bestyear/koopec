use super::{Cursor, Journal, JournalRow, RowId, RowPayload};
use std::{collections::BTreeMap, fmt};
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProjectionError {
    MissingObservation,
    DuplicateObservation,
    OutOfOrder,
}
impl fmt::Display for ProjectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for ProjectionError {}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Projection {
    values: BTreeMap<RowId, i64>,
    cursor: Cursor,
}
impl Default for Projection {
    fn default() -> Self {
        Self {
            values: BTreeMap::new(),
            cursor: Cursor::start(),
        }
    }
}
impl Projection {
    #[must_use]
    pub fn get(&self, id: RowId) -> Option<i64> {
        self.values.get(&id).copied()
    }
    #[must_use]
    pub fn len(&self) -> usize {
        self.values.len()
    }
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
    #[must_use]
    pub const fn cursor(&self) -> Cursor {
        self.cursor
    }
    /// Apply the journal suffix to this projection without changing it on error.
    pub fn update(&mut self, journal: &Journal) -> Result<(), ProjectionError> {
        let mut next = self.clone();
        for row in journal.read_after(self.cursor) {
            next.apply(row)?;
        }
        *self = next;
        Ok(())
    }
    fn apply(&mut self, row: &JournalRow) -> Result<(), ProjectionError> {
        if row.cursor() <= self.cursor {
            return Err(ProjectionError::OutOfOrder);
        }
        match row.payload {
            RowPayload::Observation { value } => {
                if self.values.contains_key(&row.id) {
                    return Err(ProjectionError::DuplicateObservation);
                }
                self.values.insert(row.id, value);
            }
            RowPayload::Recalculation { corrects, value } => {
                let old = self
                    .values
                    .get_mut(&corrects)
                    .ok_or(ProjectionError::MissingObservation)?;
                *old = value;
            }
        }
        self.cursor = row.cursor();
        Ok(())
    }
}
