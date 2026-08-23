import logging

from odoo import api, SUPERUSER_ID


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Install standard ZKTeco punch defaults and retry previously unknown events."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    devices = env["mdl.attendance.device"].sudo().search([
        ("manufacturer", "=", "zkteco"),
    ])
    for device in devices:
        values = {}
        if not (device.punch_in_values or "").strip():
            values["punch_in_values"] = "0"
        if not (device.punch_out_values or "").strip():
            values["punch_out_values"] = "1"
        if values:
            device.write(values)

    unknown_events = env["mdl.attendance.device.event"].sudo().search([
        ("device_id", "in", devices.ids),
        ("punch_state", "=", "unknown"),
        ("raw_punch_state", "!=", False),
        ("processing_state", "not in", ["processed", "ignored"]),
    ], order="event_datetime, id")
    retry_events = unknown_events.filtered(
        lambda event: event.device_id._adapter().map_punch_state(event.raw_punch_state)
        in ("in", "out")
    )
    if retry_events:
        retry_events.action_process()
        _logger.info(
            "Retried %s previously unmapped ZKTeco attendance event(s)",
            len(retry_events),
        )
