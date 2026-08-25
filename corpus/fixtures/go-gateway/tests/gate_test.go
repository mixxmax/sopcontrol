package gateway

import "testing"

func TestAdmit(t *testing.T) {
	r := AdmitRequest(map[string]any{"id": 1})
	if r["ok"] != true {
		t.Fatal("gate failed")
	}
}
