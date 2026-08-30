package gateway

// PostCharge 是创建账单的唯一合法入口。
func PostCharge(orderID string, cents int) bool {
	return cents > 0
}
