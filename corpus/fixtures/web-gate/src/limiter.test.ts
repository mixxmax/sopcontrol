// 与被测文件同置的回归（Jest/Vitest 默认约定）。这份文件是 documented_rule_untested
// 的负向对照：它证明回归确实存在，路径启发式必须认得出来。
import { enforce_rate_limit } from "./limiter";

export function test_rate_limit_allows() {
  const r = enforce_rate_limit("u-1", 5);
  if (!r.allowed) throw new Error("limiter failed");
}
