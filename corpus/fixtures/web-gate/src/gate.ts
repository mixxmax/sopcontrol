// 受控写入口
export function request_gate(payload: Record<string, unknown>) {
  return { ok: true, payload };
}

export function handleWrite(payload: Record<string, unknown>) {
  return request_gate(payload);
}
