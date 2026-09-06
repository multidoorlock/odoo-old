import uuid

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    def _attendance_event_source(self):
        self.ensure_one()
        company = self.employee_id.company_id or self.env.company
        card = self.env["mdl.attendance.device.employee"].with_context(
            active_test=False,
        ).search([
            ("employee_id", "=", self.employee_id.id),
            ("device_id.company_id", "=", company.id),
        ], order="active desc, last_sync_at desc, id", limit=1)
        if card:
            return card.device_id, card
        device = self.env["mdl.attendance.device"].with_context(
            active_test=False,
        ).search([
            ("device_identifier", "=", f"odoo-attendance-{company.id}"),
        ], limit=1)
        if not device:
            device = self.env["mdl.attendance.device"].sudo().create({
                "name": "Odoo Attendance",
                "manufacturer": "zkteco",
                "device_identifier": f"odoo-attendance-{company.id}",
                "company_id": company.id,
                "active": False,
            })
        return device, self.env["mdl.attendance.device.employee"]

    def _ensure_attendance_device_events(self):
        if self.env.context.get("skip_attendance_event_sync"):
            return
        Event = self.env["mdl.attendance.device.event"].sudo()
        for attendance in self.filtered(lambda item: item.employee_id and item.check_in):
            device, card = attendance._attendance_event_source()
            log = Event.search([
                ("attendance_id", "=", attendance.id),
                ("odoo_generated", "=", True),
            ], limit=1).log_id
            if not log:
                log = self.env["mdl.attendance.device.log"].sudo().create({
                    "device_id": device.id,
                    "device_identifier": device.device_identifier,
                    "request_type": "ODOO",
                    "http_method": "ORM",
                    "endpoint": "hr.attendance",
                    "processing_state": "processed",
                    "processing_message": "Generated from Odoo attendance",
                })
            endpoints = (("in", attendance.check_in), ("out", attendance.check_out))
            for kind, value in endpoints:
                linked = Event.search([
                    ("attendance_id", "=", attendance.id),
                ], order="odoo_generated asc, id").filtered(
                    lambda event: (event.manual_punch_state or event.punch_state) == kind
                )[:1]
                if not value:
                    linked.filtered("odoo_generated").unlink()
                    continue
                if not linked:
                    linked = Event.search([
                        ("attendance_id", "=", False),
                        ("employee_id", "=", attendance.employee_id.id),
                        ("event_datetime", "=", value),
                        ("processing_state", "!=", "ignored"),
                    ], order="odoo_generated asc, id").filtered(
                        lambda event: (event.manual_punch_state or event.punch_state) == kind
                    )[:1]
                values = {
                    "employee_id": attendance.employee_id.id,
                    "event_datetime": value,
                    "processing_state": "processed",
                    "processing_message": False,
                    "attendance_id": attendance.id,
                    "conflict_dismissed": False,
                }
                if linked:
                    linked.with_context(attendance_event_system_write=True).write(values)
                    continue
                Event.with_context(attendance_event_system_write=True).create({
                    **values,
                    "log_id": log.id,
                    "device_id": device.id,
                    "device_employee_id": card.id,
                    "device_user_id": card.device_user_id if card else False,
                    "raw_line": "Odoo attendance endpoint",
                    "raw_punch_state": kind,
                    "punch_state": kind,
                    "event_fingerprint": "odoo:%s:%s:%s" % (
                        attendance.id, kind, uuid.uuid4().hex,
                    ),
                    "odoo_generated": True,
                })

    @api.model_create_multi
    def create(self, vals_list):
        attendances = super().create(vals_list)
        attendances._ensure_attendance_device_events()
        return attendances

    def write(self, vals):
        result = super().write(vals)
        if {"employee_id", "check_in", "check_out"}.intersection(vals):
            self._ensure_attendance_device_events()
        return result

    def unlink(self):
        generated = self.env["mdl.attendance.device.event"].sudo().search([
            ("attendance_id", "in", self.ids), ("odoo_generated", "=", True),
        ])
        raw_events = self.env["mdl.attendance.device.event"].sudo().search([
            ("attendance_id", "in", self.ids), ("odoo_generated", "=", False),
        ])
        result = super().unlink()
        generated.unlink()
        raw_events.with_context(attendance_event_system_write=True).write({
            "processing_state": "not_applied",
            "processing_message": "Linked attendance was deleted",
        })
        return result
