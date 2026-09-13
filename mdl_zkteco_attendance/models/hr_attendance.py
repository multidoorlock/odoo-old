import uuid

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    def _is_attendance_event_source(self):
        """Absence placeholders are payroll inputs, never physical punches."""
        self.ensure_one()
        return not (self.in_mode == "technical" and self.out_mode == "technical")

    @api.model
    def _filter_conflicting_technical_absence_vals(self, vals_list):
        """Skip only absence placeholders that overlap real attendance.

        Odoo's absence cron creates all technical rows in one batch.  One
        employee with an open or overlapping attendance would otherwise make
        the native validity constraint roll back the complete cron job.
        Ordinary attendance creation must keep raising the native validation
        error, so the protection is deliberately limited to rows whose input
        and output modes are both ``technical``.
        """
        safe_vals_list = []
        for vals in vals_list:
            check_in = fields.Datetime.to_datetime(vals.get("check_in"))
            check_out = fields.Datetime.to_datetime(vals.get("check_out"))
            is_absence_placeholder = (
                vals.get("in_mode") == "technical"
                and vals.get("out_mode") == "technical"
                and vals.get("employee_id")
                and check_in
                and check_out
            )
            if is_absence_placeholder and self.search_count([
                ("employee_id", "=", vals["employee_id"]),
                ("check_in", "<", check_out),
                "|",
                ("check_out", "=", False),
                ("check_out", ">", check_in),
            ], limit=1):
                continue
            safe_vals_list.append(vals)
        return safe_vals_list

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
        for attendance in self.filtered(
            lambda item: item.employee_id and item.check_in and item._is_attendance_event_source()
        ):
            company = attendance.employee_id.company_id or self.env.company
            device, card = attendance._attendance_event_source()
            linked_events = Event.search([
                ("attendance_id", "=", attendance.id),
            ])
            incompatible_events = linked_events.filtered(
                lambda event: event.company_id != company
            )
            if incompatible_events:
                # A legacy event can still point to an attendance whose employee
                # was moved to another company.  Keep raw clock evidence on its
                # original device/company, but do not reuse that event as an
                # endpoint for the cross-company attendance.  Generated endpoint
                # events have no source evidence and can safely be rebuilt below.
                incompatible_events.filtered("odoo_generated").unlink()
                incompatible_events.filtered(
                    lambda event: not event.odoo_generated
                ).with_context(attendance_event_system_write=True).write({
                    "attendance_id": False,
                    "processing_state": "not_applied",
                    "processing_message": (
                        "Attendance link removed because the employee belongs "
                        "to another company"
                    ),
                })
            log = Event.search([
                ("attendance_id", "=", attendance.id),
                ("odoo_generated", "=", True),
                ("company_id", "=", company.id),
            ], limit=1).log_id
            endpoints = (("in", attendance.check_in), ("out", attendance.check_out))
            for kind, value in endpoints:
                linked = Event.search([
                    ("attendance_id", "=", attendance.id),
                    ("company_id", "=", company.id),
                    ("processing_state", "!=", "ignored"),
                    ("conflict_dismissed", "=", False),
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
                        ("company_id", "=", company.id),
                        ("event_datetime", "=", value),
                        ("processing_state", "!=", "ignored"),
                        ("conflict_dismissed", "=", False),
                    ], order="odoo_generated asc, id").filtered(
                        lambda event: (event.manual_punch_state or event.punch_state) == kind
                    )[:1]
                values = {
                    "employee_id": attendance.employee_id.id,
                    "event_datetime": value,
                    "processing_state": "processed",
                    "processing_message": False,
                    "attendance_id": attendance.id,
                }
                if linked:
                    linked.with_context(attendance_event_system_write=True).write(values)
                    continue
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
        vals_list = self._filter_conflicting_technical_absence_vals(vals_list)
        if not vals_list:
            return self.browse()
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
        # Hidden generated endpoints are durable exclusion evidence. Even a
        # later native attendance deletion must not erase that decision.
        hidden_generated = generated.filtered("conflict_dismissed")
        hidden_generated.with_context(attendance_event_system_write=True).write({
            "odoo_generated": False,
        })
        generated -= hidden_generated
        raw_events = self.env["mdl.attendance.device.event"].sudo().search([
            ("attendance_id", "in", self.ids), ("odoo_generated", "=", False),
            # Rebuilding attendance must not reactivate retransmissions or
            # cooldown punches that were already rejected. Their attendance
            # reference is cleared by unlink; their rejection remains intact.
            ("processing_state", "!=", "ignored"),
        ])
        result = super().unlink()
        generated.unlink()
        raw_events.with_context(attendance_event_system_write=True).write({
            "processing_state": "not_applied",
            "processing_message": "Linked attendance was deleted",
        })
        return result
