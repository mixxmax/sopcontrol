// sopcontrol-hook v1 (marker) — sopctl hook opencode 生成；决策权在本地控制器，插件只是执行器
import { execFileSync } from "node:child_process";

const PY = "/Users/xiezhijie/sopcontrol/.venv/bin/python";
const PROJECT = "/Users/xiezhijie/sopcontrol";

export const SopControl = async () => {
  return {
    "tool.execute.before": async (input, output) => {
      let payload = null;
      if (input.tool === "bash") {
        payload = { tool_name: "Bash", tool_input: { command: output.args.command } };
      } else if (input.tool === "edit" || input.tool === "write") {
        payload = { tool_name: "Write", tool_input: { file_path: output.args.filePath ?? output.args.file_path } };
      }
      if (!payload) return; // 非受控工具：观察，不阻断
      // 能拿到当前模型就带上，供执行者身份校验（中途换模型 → rebind）
      const model =
        input.model ??
        input.session?.model ??
        input.session?.modelID ??
        process.env.OPENCODE_MODEL ??
        process.env.SOPCONTROL_MODEL ??
        "";
      if (model) payload.model = String(model);
      let decision;
      try {
        const out = execFileSync(PY, ["-m", "sopcontrol.cli", "harness-check", "--payload",
          JSON.stringify(payload), PROJECT], { encoding: "utf8" });
        decision = JSON.parse(out);
      } catch (e) {
        throw new Error("[sopcontrol] harness-check 不可用，fail-closed: " + e.message);
      }
      const d = (decision.hookSpecificOutput ?? {});
      if (d.permissionDecision === "deny") throw new Error("[sopcontrol] 拒绝: " + d.permissionDecisionReason);
      if (d.permissionDecision === "ask") throw new Error("[sopcontrol] 需人工确认: " + d.permissionDecisionReason);
    },
  };
};
