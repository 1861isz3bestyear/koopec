use market_data::bybit::interest_page;

#[test]
fn interest_page_preserves_wire_order_and_opaque_cursor() {
    let page = interest_page(r#"{"retCode":0,"result":{"nextPageCursor":"ab%3D+","list":[{"timestamp":"7200000","openInterest":"42.5"},{"timestamp":"3600000","openInterest":41}]}}"#).unwrap();
    assert_eq!(page.samples, [(7_200_000, 42.5), (3_600_000, 41.0)]);
    assert_eq!(page.cursor, "ab%3D+");
    assert_eq!(
        interest_page(r#"{"retCode":0,"result":{"list":[]}}"#)
            .unwrap()
            .cursor,
        ""
    );
}

#[test]
fn rejects_invalid_external_interest_pages() {
    for invalid in [
        "{",
        r#"{"retCode":10006}"#,
        r#"{"retCode":0,"result":{"list":null}}"#,
        r#"{"retCode":0,"result":{"list":[],"nextPageCursor":12}}"#,
        r#"{"retCode":0,"result":{"list":[{"timestamp":"1","openInterest":"2"}]}}"#,
        r#"{"retCode":0,"result":{"list":[{"timestamp":"3600000","openInterest":"NaN"}]}}"#,
        r#"{"retCode":0,"result":{"list":[{"timestamp":"3600000","openInterest":"0"}]}}"#,
        r#"{"retCode":0,"result":{"list":[{"timestamp":"3600000","openInterest":"1"},{"timestamp":"3600000","openInterest":"2"}]}}"#,
    ] {
        assert!(interest_page(invalid).is_err(), "{invalid}");
    }
}
