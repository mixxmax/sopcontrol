package api

import "testing"

// charge_test.go 自带同名替身：这里测的是本包的 stub，不是 gateway.PostCharge。
// 真实 Go 项目里这个文件能编译、测试能全绿——生产实现从未被 import，生产端
// 改名或改语义这里毫无察觉。go_ast 的包/import 证据让 reachability 能识破它。
type chargeRequest struct {
	orderID string
	cents   int
}

func PostCharge(req chargeRequest) bool {
	return req.cents > 0
}

func TestPostChargeStub(t *testing.T) {
	if !PostCharge(chargeRequest{orderID: "o-1", cents: 100}) {
		t.Fatal("stub charge failed")
	}
}
