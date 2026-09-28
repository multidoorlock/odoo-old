import logging
from datetime import datetime, timedelta

from psycopg2.errors import DeadlockDetected, SerializationFailure

from odoo import _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class AttendanceProcessor:
    def __init__(self, env):
        self.env = env

    def _invalid_company_binding_message(self):
        return self.env._(
            "כרטיס השעון מקושר לעובד מחברה אחרת. "
            "יש לקשר את הכרטיס לעובד מאותה חברה של השעון."
        )

    def process(self, events):
        # Share the timeline editor's lock order, and acquire every affected
        # employee up front.  Taking one employee lock per chronological punch
        # would invert that order for batches covering several employees.
        valid_employee_events = events.sudo().filtered(lambda event: (
            event.employee_id and event.employee_id.company_id == event.device_id.company_id
        ))
        employee_ids = set(valid_employee_events.mapped("employee_id").ids)
        cards = events.sudo().mapped("device_employee_id")
        unbound = events.filtered(
            lambda event: not event.device_employee_id
            and event.device_id and event.device_user_id
        )
        if unbound:
            keys = {(event.device_id.id, event.device_user_id) for event in unbound}
            cards |= self.env["mdl.attendance.device.employee"].sudo().search([
                ("device_id", "in", list({key[0] for key in keys})),
                ("device_user_id", "in", list({key[1] for key in keys})),
            ]).filtered(lambda card: (card.device_id.id, card.device_user_id) in keys)
        valid_cards = cards.filtered(lambda card: (
            card.employee_id and card.employee_id.company_id == card.device_id.company_id
        ))
        employee_ids.update(valid_cards.mapped("employee_id").ids)
        self.env["mdl.attendance.device.event"]._timeline_lock_employee_ids(employee_ids)
        # Selection and the initial employee lookup may have prefetched an
        # event before another request excluded it.  Read its current state
        # after the same fence used by Hide before applying any punch.
        events.invalidate_recordset()
        for event in events.sorted(key=lambda e: (e.event_datetime or datetime.min, e.id)):
            try:
                with self.env.cr.savepoint():
                    self._process_one(event)
            except (DeadlockDetected, SerializationFailure):
                raise
            except Exception as exc:
                _logger.exception("Attendance event %s failed", event.id)
                event.sudo().write({"processing_state": "error", "processing_message": str(exc)})
        affected_employee_ids = events.sudo().filtered(lambda event: (
            event.employee_id and event.employee_id.company_id == event.device_id.company_id
        )).mapped("employee_id").ids
        if affected_employee_ids:
            self.env["mdl.attendance.device.event"]._timeline_reconcile_employee_ids(
                affected_employee_ids,
            )

    def _process_one(self, event):
        # Hide is a processing exclusion, not just a timeline display flag.
        # Keep the source and fingerprint so a clock replay stays deduplicated,
        # but never let a retry, card relink or manual reprocess apply it again.
        if event.conflict_dismissed or event.processing_state in ("processed", "ignored"):
            return
        if not event.manual_punch_state and event.punch_state == "unknown" and event.raw_punch_state:
            mapped_state = event.device_id._adapter().map_punch_state(event.raw_punch_state)
            if mapped_state != "unknown":
                event.sudo().write({"punch_state": mapped_state})
        duplicate = self.env["mdl.attendance.device.event"].sudo().search([
            # The fingerprint describes the immutable clock punch, regardless
            # of whether its first occurrence could be paired yet.  In
            # particular, retransmitting an unmatched or hidden punch must
            # not create another visible conflict (or resurrect a hidden one).
            # Only earlier records are canonical: a later replay must never
            # prevent processing the original after its employee is linked.
            ("id", "<", event.id),
            ("device_id", "=", event.device_id.id),
            ("event_fingerprint", "=", event.event_fingerprint),
        ], order="id", limit=1)
        if duplicate:
            duplicate_attendance = duplicate.attendance_id.filtered(lambda attendance: (
                attendance.employee_id.company_id == event.device_id.company_id
            ))
            event.sudo().write({"processing_state": "ignored", "processing_message": "Duplicate retransmission", "attendance_id": duplicate_attendance.id})
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
        if card.employee_id.company_id != event.device_id.company_id:
            # Legacy card mappings can predate the company constraint.  This
            # is a configuration issue, not a malformed timestamp or punch.
            # Keep its raw evidence and card; never guess a replacement person.
            event.sudo().with_context(attendance_event_system_write=True).write({
                "employee_id": False,
                "processing_state": "waiting_employee_link",
                "processing_message": self._invalid_company_binding_message(),
            })
            return
        event.sudo().with_context(attendance_event_system_write=True).write({
            "employee_id": card.employee_id.id,
        })
        effective_punch_state = event.manual_punch_state or event.punch_state
        if effective_punch_state == "unknown":
            event.sudo().write({"processing_state": "not_applied", "processing_message": f"Unmapped punch state: {event.raw_punch_state}"})
            return
        cooldown_source = self._cooldown_source_event(
            event, card, effective_punch_state,
        )
        if cooldown_source:
            punch_label = _("Entry") if effective_punch_state == "in" else _("Exit")
            event.sudo().write({
                "processing_state": "ignored",
                "processing_message": _(
                    "סונן בעזרת Cooldown: החתמת %(punch)s נוספת "
                    "בתוך %(minutes)s דקות.",
                    punch=punch_label,
                    minutes=event.device_id.attendance_cooldown_minutes,
                ),
                "attendance_id": cooldown_source.attendance_id.id,
            })
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

    def _cooldown_source_event(self, event, card, punch_state):
        """Return the last accepted same-kind punch inside the device window."""
        minutes = event.device_id.attendance_cooldown_minutes
        if minutes <= 0 or not event.event_datetime or punch_state not in ("in", "out"):
            return self.env["mdl.attendance.device.event"]

        candidates = self.env["mdl.attendance.device.event"].sudo().search([
            ("id", "!=", event.id),
            ("device_id", "=", event.device_id.id),
            ("device_employee_id", "=", card.id),
            ("event_datetime", ">=", event.event_datetime - timedelta(minutes=minutes)),
            ("event_datetime", "<=", event.event_datetime),
            ("processing_state", "!=", "ignored"),
            ("conflict_dismissed", "=", False),
        ], order="event_datetime desc, id desc")
        return candidates.filtered(
            lambda candidate: (
                candidate.event_datetime < event.event_datetime
                or candidate.id < event.id
            )
            and (candidate.manual_punch_state or candidate.punch_state) == punch_state
        )[:1]
