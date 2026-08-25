import { request_gate } from "../src/gate";

export function test_gated() {
  const r = request_gate({ id: 1 });
  if (!r.ok) throw new Error("gate failed");
}
