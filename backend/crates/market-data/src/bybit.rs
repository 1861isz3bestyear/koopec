//! Validate the hourly Bybit open-interest response before pagination.
use serde_json::Value;

#[derive(Debug, PartialEq)]
pub struct InterestPage {
    pub samples: Vec<(i64, f64)>,
    pub cursor: String,
}

pub fn interest_page(payload: &str) -> Result<InterestPage, &'static str> {
    let body: Value = serde_json::from_str(payload).map_err(|_| "Invalid Bybit OI JSON")?;
    if body.get("retCode").and_then(Value::as_i64) != Some(0) {
        return Err("Bybit OI request failed");
    }
    let result = &body["result"];
    let rows = result["list"].as_array().ok_or("Invalid Bybit OI list")?;
    let cursor = match result.get("nextPageCursor") {
        Some(value) => value.as_str().ok_or("Invalid Bybit OI cursor")?,
        None => "",
    };
    let mut samples = Vec::with_capacity(rows.len());
    for row in rows {
        let timestamp = row["timestamp"]
            .as_str()
            .filter(|value| value.bytes().all(|byte| byte.is_ascii_digit()))
            .and_then(|value| value.parse::<i64>().ok())
            .filter(|value| (1..=253_402_300_799_000).contains(value) && value % 3_600_000 == 0)
            .ok_or("OI timestamps must be positive hourly epoch milliseconds")?;
        let interest = super::number(&row["openInterest"])
            .ok()
            .filter(|value| *value > 0.0)
            .ok_or("OI quantities must be positive finite values")?;
        if samples
            .last()
            .is_some_and(|(previous, _)| *previous <= timestamp)
        {
            return Err("Bybit OI page must be strictly reverse chronological");
        }
        samples.push((timestamp, interest));
    }
    Ok(InterestPage {
        samples,
        cursor: cursor.into(),
    })
}
