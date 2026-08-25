fn admit_request(payload: &str) -> bool {
    !payload.is_empty()
}

#[test]
fn test_admit() {
    assert!(admit_request("x"));
}
