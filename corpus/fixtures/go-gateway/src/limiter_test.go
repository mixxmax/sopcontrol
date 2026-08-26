package gateway

import "testing"

// Go 的回归只能与被测文件同目录同包——这不是可选风格，是语言约定。
// documented_rule_untested 的负向对照第二域。
func TestEnforceRateLimit(t *testing.T) {
	if !EnforceRateLimit("u-1", 5) {
		t.Fatal("limiter failed")
	}
}
