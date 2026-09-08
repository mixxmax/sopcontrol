"""发布版本元数据必须与导入时暴露的版本保持一致。"""
from importlib.metadata import version

import sopcontrol
from sopcontrol import events, tickets


def test_imported_version_matches_distribution_metadata():
    assert sopcontrol.__version__ == version("sopcontrol")


def test_schema_pins_are_exported():
    assert sopcontrol.API_SERIES == "0.2"
    assert sopcontrol.TICKET_SCHEMA_VERSION == tickets.SCHEMA_VERSION
    assert sopcontrol.EVENT_SCHEMA_VERSION == events.SCHEMA_VERSION
    assert sopcontrol.CAPABILITY_EVENT_SCHEMA_VERSION == 2
