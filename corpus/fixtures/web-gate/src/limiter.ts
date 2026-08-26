// 限流是生产代码；回归写在同目录的 limiter.test.ts 里（TS 生态的同置约定）。
// 只认 tests/ 目录的路径启发式会把那份回归读成生产文件，于是「有回归」被判成
// documented_rule_untested——在完全正确的代码上报警。
export function enforce_rate_limit(key: string, quota: number) {
  return { key, quota, allowed: quota > 0 };
}
