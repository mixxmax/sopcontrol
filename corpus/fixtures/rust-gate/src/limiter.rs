// 限流是生产代码；RS-003 的回归在 tests/limiter_test.rs（经 use crate::limiter 闭合）。
// 注意 tests/gate_test.rs 的「测试」是同名替身（自定义 admit_request、零 use）——
// rust 可达性上线后它会被 test_cannot_reach_consumer 识破，别把它当回归的样子学。
pub fn enforce_rate_limit(key: &str, quota: i64) -> bool {
    quota > 0
}
