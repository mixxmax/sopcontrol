package gateway

// EnforceRateLimit 是生产代码；Go 强制回归与被测文件同目录同包（limiter_test.go）。
// 把 _test.go 当生产文件，就会把「有回归」判成 documented_rule_untested。
func EnforceRateLimit(key string, quota int) bool {
	return quota > 0
}
