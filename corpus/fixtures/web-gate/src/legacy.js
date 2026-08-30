// 旧链清理的受控入口——.js 遗留文件（TS 项目里的 JS 残余是常态）。
// 按设计 .js 家族不走 tree-sitter 结构化，判定依据是词法代理，
// grounding 必须如实自曝 lexical——这正是本文件存在的目的：语料层
// 永远保留一个「pass 但只是搜到了标识符」的正向对照。
export function legacy_gate(payload) {
  return { ok: true, payload };
}
