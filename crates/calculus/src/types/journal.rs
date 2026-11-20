use super::Micros;
use std::{collections::BTreeSet, fmt};
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default)]
pub struct CommitSeq(pub u64);
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RowId(pub u64);
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Cursor {
    pub commit_seq: CommitSeq,
    pub row_id: RowId,
}
impl Cursor {
    #[must_use]
    pub const fn start() -> Self {
        Self {
            commit_seq: CommitSeq(0),
            row_id: RowId(0),
        }
    }
}
impl fmt::Display for Cursor {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:{}", self.commit_seq.0, self.row_id.0)
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JournalRow {
    pub id: RowId,
    pub commit_seq: CommitSeq,
    pub available_at: Micros,
    pub payload: RowPayload,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RowPayload {
    Observation { value: i64 },
    Recalculation { corrects: RowId, value: i64 },
}
impl JournalRow {
    #[must_use]
    pub const fn cursor(&self) -> Cursor {
        Cursor {
            commit_seq: self.commit_seq,
            row_id: self.id,
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JournalError {
    EmptyCommit,
    NonIncreasingCommit,
    MixedCommit,
    DuplicateRowId,
    MissingObservation,
}
impl fmt::Display for JournalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for JournalError {}
/// In-memory model: each complete batch is validated then published atomically.
/// Persistent implementations must allocate sequences and publish in one transaction.
#[derive(Debug, Default)]
pub struct Journal {
    rows: Vec<JournalRow>,
    horizon: CommitSeq,
    ids: BTreeSet<RowId>,
    observations: BTreeSet<RowId>,
}
impl Journal {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
    pub fn commit(&mut self, mut rows: Vec<JournalRow>) -> Result<(), JournalError> {
        let seq = rows.first().ok_or(JournalError::EmptyCommit)?.commit_seq;
        if seq <= self.horizon {
            return Err(JournalError::NonIncreasingCommit);
        }
        if rows.iter().any(|row| row.commit_seq != seq) {
            return Err(JournalError::MixedCommit);
        }
        rows.sort_by_key(JournalRow::cursor);
        let mut ids = self.ids.clone();
        let mut observations = self.observations.clone();
        for row in &rows {
            if !ids.insert(row.id) {
                return Err(JournalError::DuplicateRowId);
            }
            match row.payload {
                RowPayload::Observation { .. } => {
                    observations.insert(row.id);
                }
                RowPayload::Recalculation { corrects, .. } => {
                    if !observations.contains(&corrects) {
                        return Err(JournalError::MissingObservation);
                    }
                }
            }
        }
        self.ids = ids;
        self.observations = observations;
        self.rows.extend(rows);
        self.horizon = seq;
        Ok(())
    }
    #[must_use]
    pub fn read_after(&self, after: Cursor) -> Vec<&JournalRow> {
        self.rows
            .iter()
            .filter(|row| row.cursor() > after)
            .collect()
    }
    #[must_use]
    pub fn advance_cursor(&self, after: Cursor) -> Cursor {
        self.read_after(after)
            .last()
            .map_or(after, |row| row.cursor())
    }
}
