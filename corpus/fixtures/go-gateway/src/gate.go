package gateway

// AdmitRequest 是唯一合法写入口。
func AdmitRequest(payload map[string]any) map[string]any {
	return map[string]any{"ok": true, "payload": payload}
}

func HandleWrite(payload map[string]any) map[string]any {
	return AdmitRequest(payload)
}
