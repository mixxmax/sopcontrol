// RS-003 的真实集成测试：经 use 引入生产模块符号（Rust 集成测试是独立 crate，
// 不 use 生产 crate 就只能定义替身——gate_test.rs 那种，正是要被识破的形态）。
use crate::limiter::enforce_rate_limit;

#[test]
fn test_rate_limit_allows() {
    assert!(enforce_rate_limit("u-1", 5));
}
