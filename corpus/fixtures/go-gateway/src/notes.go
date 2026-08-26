package gateway

// 交接备注（Go 表面的 comment_only_reference 负向对照）。
// 真引用在 gate.go：HandleWrite 调用 AdmitRequest。这里只是散文提及。
// 同夹具里 RegisterAuditHook 是真断口，检测器要能分辨两者。

// OnboardingNotes 列出新人阅读顺序。
func OnboardingNotes() []string {
	// 先读 AdmitRequest 的入参约定，再看超时（这一行是文档，不是引用）
	return []string{"读入参约定", "读超时设置", "读回滚路径"}
}
