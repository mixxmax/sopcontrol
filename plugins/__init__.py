"""插件登记处。骨架期显式注册；外部插件目录加载是后续插卡点，不是现在的需求。"""
from plugins.detectors.no_consumer import NoConsumerDetector
from plugins.detectors.reachability import ReachabilityDetector
from plugins.detectors.state_health import StateHealthDetector
from plugins.sensors.ast_scan import AstScanSensor
from plugins.sensors.code_scan import CodeScanSensor
from plugins.sensors.doc_scan import DocScanSensor
from plugins.sensors.go_scan import GoScanSensor
from plugins.sensors.import_graph import ImportGraphSensor
from plugins.sensors.js_scan import JsScanSensor
from plugins.sensors.rust_scan import RustScanSensor
from plugins.sensors.trace_scan import TraceScanSensor

SENSORS = [
    CodeScanSensor(), DocScanSensor(), AstScanSensor(),
    JsScanSensor(), GoScanSensor(), RustScanSensor(), ImportGraphSensor(),
    TraceScanSensor(),
]
DETECTORS = [NoConsumerDetector(), StateHealthDetector(), ReachabilityDetector()]
