# Reference Host — API / Worker

> 这是本地参考宿主，明确不是 JobsFlow 证据，也不是任何真实业务系统。

这个 fixture 把宿主侧业务形状保持在 Python API 内：

- `run_batch(inputs)`：输入集合到输出集合，输出带最小 `from` 沿袭字段；
- `expensive_op_descriptor()`：声明一个高成本 scorer operator；
- `run_expensive(inputs, admit=...)`：昂贵动作要求调用方注入 admission callback；
- `narrow(items, predicate)`：缩小集合，演示在昂贵步骤前下推谓词；
- `business_check(outputs)`：业务检查 stub；
- `run_with_retry(text)`：一次有界失败重试路径。

## 运行

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
import importlib.util
from pathlib import Path

path = Path('corpus/fixtures/reference-host-worker/host_worker.py')
spec = importlib.util.spec_from_file_location('reference_host_worker', path)
worker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(worker)

batch = worker.run_batch([{'id': 'a', 'text': 'xyz'}, {'id': 'b', 'text': ''}])
print(batch)
print(worker.expensive_op_descriptor())
print(worker.run_expensive(batch['outputs'], admit=lambda context: True))
print(worker.narrow(batch['outputs'], lambda item: item['score'] > 0))
print(worker.business_check([{'id': 'bad', 'score': -1}]))
print(worker.run_with_retry('abcd'))
PY
```

预期输出包含两个 input/output id、`is_expensive: True`、一个经过 callback
放行的 expensive 结果、缩小后的 `a`、一个 blocking stub finding，以及
`attempts: 2`。这里的 `lambda context: True` 只是 fixture 演练，不是授权证据。

## 与 SOP Control 的接线点

宿主保留 `admit` 注入点，而不是把规则或 ticket 逻辑伪装成业务代码。正式 adapter
可以在 callback 中消费项目自己的 `bridge admit` / operator admission 结果；本
fixture 只验证接口形状、输入/输出集合和失败重试路径可被接入。

它不证明真实 worker、队列、外部服务、业务检查、模型调用或 JobsFlow 已经接入。
