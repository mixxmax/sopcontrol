"""插件登记处。骨架期显式注册；外部插件目录加载是后续插卡点，不是现在的需求。"""
from plugins.detectors.no_consumer import NoConsumerDetector
from plugins.detectors.reachability import ReachabilityDetector
from plugins.detectors.state_health import StateHealthDetector
from plugins.sensors.ast_scan import AstScanSensor
from plugins.sensors.code_scan import CodeScanSensor
from plugins.sensors.doc_scan import DocScanSensor
from plugins.sensors.import_graph import ImportGraphSensor
from plugins.sensors.js_scan import JsScanSensor
from plugins.sensors.rust_scan import RustScanSensor
from plugins.sensors.trace_scan import TraceScanSensor

# Go 表面的视力取决于 tree-sitter 是否可用：在则 AST 级（go_ast_scan，grounding
# 标 structural），不在则退回词法代理（go_scan，grounding 如实标 lexical）。
# 判定依据强度按证据 kind 自曝，降级对用户可见而不是静默丢失（16.4）。
try:
    from plugins.sensors.go_ast_scan import GoAstScanSensor

    _GO_SENSOR = GoAstScanSensor()
except ImportError:
    from plugins.sensors.go_scan import GoScanSensor

    _GO_SENSOR = GoScanSensor()

SENSORS = [
    CodeScanSensor(), DocScanSensor(), AstScanSensor(),
    JsScanSensor(), _GO_SENSOR, RustScanSensor(), ImportGraphSensor(),
    TraceScanSensor(),
]
DETECTORS = [NoConsumerDetector(), StateHealthDetector(), ReachabilityDetector()]
