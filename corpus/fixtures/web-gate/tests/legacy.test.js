// legacy_gate 的回归引用（.js 家族无 import 证据，reachability 按沉默边界不判，
// 判定停在词法代理的 wired_and_tested——诚实但 weaker，这正是要对照的形态）。
export function test_legacy_gate() {
  const r = legacy_gate({ id: 1 });
  if (!r.ok) throw new Error("legacy gate failed");
}
