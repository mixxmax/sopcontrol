// 交接备注（TS 表面的 comment_only_reference 负向对照）。
// 真引用在 gate.ts：handleWrite 调用 request_gate。这里只是散文提及。
// 同文件里 audit_hook 是真断口（ghost.ts），两者混在同一夹具里——检测器要能
// 分辨「只存在于注释」和「别处真调用、这里顺手提一句」。
export function onboardingNotes() {
  // 新人先读 request_gate 的入参约定，再看重试策略（这一行是文档，不是引用）
  return ["读入参约定", "读重试策略", "读回滚路径"];
}
