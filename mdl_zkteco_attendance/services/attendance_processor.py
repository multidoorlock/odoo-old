import logging
from datetime import datetime

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AttendanceProcessor:
    def __init__(self, env):
        self.env = env

    def process(self, events):
        for event in events.sorted(key=lambda e: (e.event_datetime or datetime.min, e.id)):
            try:
                self._process_one(event)
            except Exception as exc:
                _logger.exception("Attendance event %s failed", event.id)
                event.sudo().write({"processing_state": "error", "processing_message": str(exc)})
        affected_employee_ids = events.sudo().mapped("employee_id").ids
        if affected_employee_ids:
            self.env["mdl.attendance.device.event"]._timeline_reconcile_employee_ids(
                affected_employee_ids,
            )

    def _process_one(self, event):
        if event.processing_state in ("processed", "ignored"):
            return
        if not event.manual_punch_state and event.punch_state == "unknown" and event.raw_punch_state:
            mapped_state = event.device_id._adapter().map_punch_state(event.raw_punch_state)
            if mapped_state != "unknown":
                event.sudo().write({"punch_state": mapped_state})
        duplicate = self.env["mdl.attendance.device.event"].sudo().search([
            ("id", "!=", event.id), ("event_fingerprint", "=", event.event_fingerprint),
            ("processing_state", "=", "processed"),
        ], order="id", limit=1)
        if duplicate:
            event.sudo().write({"processing_state": "ignored", "processing_message": "Duplicate retransmission", "attendance_id": duplicate.attendance_id.id})
            return
        card = event.device_employee_id
        if not card and event.device_id and event.device_user_id:
            card = self.env["mdl.attendance.device.employee"].sudo().search([
                ("device_id", "=", event.device_id.id),
                ("device_user_id", "=", event.device_user_id),
            ], limit=1)
            if card:
                event.sudo().write({"device_employee_id": card.id})
        if not card or not card.employee_id:
            event.sudo().write({"processing_state": "waiting_employee_link", "processing_message": "Device card is not linked to an employee"})
            return
        event.sudo().with_context(attendance_event_system_write=True).write({
            "employee_id": card.employee_id.id,
        })
        effective_punch_state = event.manual_punch_state or event.punch_state
        if effective_punch_state == "unknown":
            event.sudo().write({"processing_state": "not_applied", "processing_message": f"Unmapped punch state: {event.raw_punch_state}"})
            return
        Attendance = self.env["hr.attendance"].sudo()
        open_attendance = Attendance.search([("employee_id", "=", card.employee_id.id), ("check_out", "=", False)], order="check_in desc", limit=1)
        if effective_punch_state == "in":
            if open_attendance:
                event.sudo().write({"processing_state": "not_applied", "processing_message": "Employee already has an open attendance", "attendance_id": open_attendance.id})
                return
            try:
                with self.env.cr.savepoint():
                    attendance = Attendance.create({"employee_id": card.employee_id.id, "check_in": event.event_datetime})
            except ValidationError as exc:
                event.sudo().write({"processing_state": "not_applied", "processing_message": str(exc)})
                return
        else:
            if not open_attendance:
                event.sudo().write({"processing_state": "not_applied", "processing_message": "No open attendance found"})
                return
            try:
                with self.env.cr.savepoint():
                    open_attendance.write({"check_out": event.event_datetime})
                attendance = open_attendance
            except ValidationError as exc:
                event.sudo().write({"processing_state": "not_applied", "processing_message": str(exc), "attendance_id": open_attendance.id})
                return
        event.sudo().write({"processing_state": "processed", "processing_message": False, "attendance_id": attendance.id})
