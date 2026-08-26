//! 交接备注（Rust 表面的 comment_only_reference 负向对照）。
//!
//! 真引用在 gate.rs：handle_write 调用 admit_request。这里只是散文提及。
//! 同夹具里 register_audit_hook 是真断口，检测器要能分辨两者。

pub fn onboarding_notes() -> Vec<&'static str> {
    // 先读 admit_request 的入参约定，再看超时（这一行是文档，不是引用）
    vec!["读入参约定", "读超时设置", "读回滚路径"]
}
