//! Integration risk: corrections must reach projections in commit order.

use calculus::types::{
    CommitSeq, Cursor, Journal, JournalRow, Micros, Projection, RowId, RowPayload,
};

fn row(id: u64, sequence: u64, payload: RowPayload) -> JournalRow {
    JournalRow {
        id: RowId(id),
        commit_seq: CommitSeq(sequence),
        available_at: Micros(0),
        payload,
    }
}

#[test]
fn successive_corrections_replay_to_the_same_projection() {
    let mut journal = Journal::new();
    let mut incremental = Projection::default();
    journal
        .commit(vec![row(1, 1, RowPayload::Observation { value: 10 })])
        .unwrap();
    incremental.update(&journal).unwrap();
    let first_cursor = incremental.cursor();
    journal
        .commit(vec![row(
            2,
            2,
            RowPayload::Recalculation {
                corrects: RowId(1),
                value: 20,
            },
        )])
        .unwrap();
    incremental.update(&journal).unwrap();
    assert_eq!(incremental.get(RowId(1)), Some(20));
    journal
        .commit(vec![row(
            3,
            3,
            RowPayload::Recalculation {
                corrects: RowId(1),
                value: 15,
            },
        )])
        .unwrap();
    incremental.update(&journal).unwrap();
    assert_eq!(incremental.get(RowId(1)), Some(15));
    assert_eq!(journal.read_after(first_cursor).len(), 2);
    assert_eq!(
        journal.advance_cursor(Cursor::start()),
        incremental.cursor()
    );
    let mut replay = Projection::default();
    replay.update(&journal).unwrap();
    assert_eq!(replay, incremental);
}
