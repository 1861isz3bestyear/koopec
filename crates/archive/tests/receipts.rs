use archive::{Archive, ArchiveError, Receipt, ReceiptBody};

fn receipt(id: &str, body: ReceiptBody) -> Receipt {
    Receipt {
        id: id.into(),
        source: "exchange".into(),
        requested_at: 10,
        available_at: 20,
        body,
    }
}

#[test]
fn receipts_are_committed_with_distinct_identity_and_cutoff() {
    let path = std::env::temp_dir().join(format!("koopec-archive-{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let body = ReceiptBody::Payload(b"0.10000000000000001\0".to_vec());
    let one = receipt("one", body.clone());
    let two = receipt("two", body);
    let mut archive = Archive::open(&path).unwrap();
    let first = archive.append(&one).unwrap();
    let second = archive.append(&two).unwrap();
    assert!(second > first);
    assert_eq!(archive.get("two", first).unwrap(), None);
    assert_eq!(archive.get("one", first).unwrap().unwrap().receipt, one);
    assert!(matches!(
        archive.append(&one),
        Err(ArchiveError::Database(_))
    ));
    drop(archive);
    let reopened = Archive::open(&path).unwrap();
    assert_eq!(reopened.get("two", second).unwrap().unwrap().receipt, two);
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn invalid_receipts_do_not_commit_and_failures_are_preserved() {
    let mut archive = Archive::open(":memory:").unwrap();
    let invalids = [
        Receipt {
            id: "".into(),
            ..receipt("a", ReceiptBody::Payload(vec![]))
        },
        Receipt {
            source: " ".into(),
            ..receipt("b", ReceiptBody::Payload(vec![]))
        },
        Receipt {
            available_at: 9,
            ..receipt("c", ReceiptBody::Payload(vec![]))
        },
        receipt("d", ReceiptBody::Failure(" ".into())),
    ];
    for invalid in invalids {
        assert!(matches!(
            archive.append(&invalid),
            Err(ArchiveError::InvalidReceipt)
        ));
        assert!(archive.get(&invalid.id, i64::MAX).unwrap().is_none());
    }
    let failure = receipt("error", ReceiptBody::Failure("timeout".into()));
    let seq = archive.append(&failure).unwrap();
    assert_eq!(archive.get("error", seq).unwrap().unwrap().receipt, failure);
}

#[test]
fn unsupported_schema_is_rejected() {
    let path = std::env::temp_dir().join(format!("koopec-version-{}.sqlite", std::process::id()));
    let _ = std::fs::remove_file(&path);
    let connection = rusqlite::Connection::open(&path).unwrap();
    connection.pragma_update(None, "user_version", 2).unwrap();
    drop(connection);
    assert!(matches!(
        Archive::open(&path),
        Err(ArchiveError::InvalidReceipt)
    ));
    std::fs::remove_file(path).unwrap();
}
