pub fn admit_request(payload: &str) -> bool {
    !payload.is_empty()
}

pub fn handle_write(payload: &str) -> bool {
    admit_request(payload)
}
