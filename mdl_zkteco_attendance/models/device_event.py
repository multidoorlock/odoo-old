from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AttendanceDeviceEvent(models.Model):
    _name = "mdl.attendance.device.event"
    _description = "Attendance Device Parsed Event"
    _order = "event_datetime desc, id desc"
    _check_company_auto = True

    log_id = fields.Many2one("mdl.attendance.device.log", required=True, ondelete="cascade", index=True)
    device_id = fields.Many2one("mdl.attendance.device", required=True, ondelete="restrict", index=True, check_company=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, index=True)
    device_employee_id = fields.Many2one("mdl.attendance.device.employee", ondelete="set null", index=True, check_company=True)
    employee_id = fields.Many2one("hr.employee", ondelete="set null", index=True, check_company=True)
    device_user_id = fields.Char(readonly=True, index=True)
    event_datetime = fields.Datetime(index=True)
    raw_line = fields.Text(readonly=True)
    raw_punch_state = fields.Char(readonly=True, index=True)
    punch_state = fields.Selection([("in", "כניסה"), ("out", "יציאה"), ("unknown", "לא ידוע")], required=True, default="unknown", readonly=True, index=True)
    event_fingerprint = fields.Char(required=True, readonly=True, index=True)
    processing_state = fields.Selection([
        ("new", "חדש"), ("processed", "עובד"), ("waiting_employee_link", "ממתין לקישור עובד"),
        ("not_applied", "לא יושם"), ("ignored", "התעלם"), ("error", "שגיאה"),
    ], default="new", required=True, readonly=True, index=True)
    processing_message = fields.Text(readonly=True)
    attendance_id = fields.Many2one("hr.attendance", readonly=True, ondelete="set null", index=True)
    manual_punch_state = fields.Selection(
        [("in", "כניסה"), ("out", "יציאה")],
        string="סוג מתוקן ידנית", copy=False, index=True,
    )
    effective_punch_state = fields.Selection(
        [("in", "כניסה"), ("out", "יציאה"), ("unknown", "לא ידוע")],
        compute="_compute_effective_punch_state", inverse="_inverse_effective_punch_state",
        string="סוג אפקטיבי",
    )
    timeline_pair_event_id = fields.Many2one(
        "mdl.attendance.device.event", string="כניסה מחוברת ידנית",
        readonly=True, copy=False, index=True, ondelete="set null",
    )
    timeline_pair_attendance_id = fields.Many2one(
        "hr.attendance", string="נוכחות מחוברת ידנית",
        readonly=True, copy=False, index=True, ondelete="set null",
    )
    timeline_blocked_in_event_ids = fields.Many2many(
        "mdl.attendance.device.event",
        "mdl_attendance_event_blocked_pair_rel",
        "out_event_id", "in_event_id",
        string="כניסות שנותקו",
        readonly=True, copy=False,
    )
    timeline_blocked_attendance_ids = fields.Many2many(
        "hr.attendance",
        "mdl_attendance_event_blocked_attendance_rel",
        "out_event_id", "attendance_id",
        string="נוכחויות שנותקו",
        readonly=True, copy=False,
    )
    conflict_action_failed = fields.Boolean(default=False, readonly=True, copy=False, index=True)
    conflict_action_error = fields.Text(readonly=True, copy=False)
    conflict_dismissed = fields.Boolean(default=False, readonly=True, index=True, copy=False)
    conflict_reason = fields.Char(compute="_compute_conflict_reason", string="סיבת הקונפליקט")
    original_event_datetime = fields.Datetime(readonly=True, copy=False)
    original_employee_id = fields.Many2one(
        "hr.employee", readonly=True, copy=False, ondelete="set null", check_company=True,
    )
    original_device_employee_id = fields.Many2one(
        "mdl.attendance.device.employee", readonly=True, copy=False,
        ondelete="set null", check_company=True,
    )
    original_values_initialized = fields.Boolean(default=True, readonly=True, copy=False)
    timeline_is_edited = fields.Boolean(
        compute="_compute_timeline_is_edited", string="נערך ידנית",
    )

    def init(self):
        """Use the values present at installation time as the legacy baseline."""
        self.env.cr.execute("""
            UPDATE mdl_attendance_device_event
               SET original_event_datetime = COALESCE(original_event_datetime, event_datetime),
                   original_employee_id = COALESCE(original_employee_id, employee_id),
                   original_device_employee_id = COALESCE(
                       original_device_employee_id, device_employee_id
                   ),
                   original_values_initialized = TRUE
             WHERE NOT COALESCE(original_values_initialized, FALSE)
        """)

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []
        for incoming_vals in vals_list:
            vals = dict(incoming_vals)
            if "original_event_datetime" not in vals:
                vals["original_event_datetime"] = vals.get("event_datetime")
            if "original_employee_id" not in vals:
                vals["original_employee_id"] = vals.get("employee_id")
            if "original_device_employee_id" not in vals:
                vals["original_device_employee_id"] = vals.get("device_employee_id")
            vals.setdefault("original_values_initialized", True)
            prepared_vals_list.append(vals)
        return super().create(prepared_vals_list)

    @api.depends("manual_punch_state", "punch_state")
    def _compute_effective_punch_state(self):
        for event in self:
            event.effective_punch_state = event.manual_punch_state or event.punch_state

    def _inverse_effective_punch_state(self):
        for event in self:
            selected = event.effective_punch_state
            event.manual_punch_state = (
                False if selected == event.punch_state else selected
            )

    @api.model
    def _timeline_raw_log_values(self, event):
        """Read the immutable ATTLOG line instead of trusting editable event fields."""
        if event.log_id.request_type != "ATTLOG" or not event.raw_line:
            return False
        try:
            columns = event.raw_line.split("\t")
            if len(columns) < 4:
                columns = event.raw_line.split()
                if len(columns) >= 5:
                    columns = [columns[0], f"{columns[1]} {columns[2]}", *columns[3:]]
            punch_column = event.device_id.punch_state_column
            if len(columns) < 2 or punch_column < 0 or punch_column >= len(columns):
                return False
            source_pin = columns[0].strip()
            local_datetime = datetime.strptime(columns[1].strip(), "%Y-%m-%d %H:%M:%S")
            timezone = pytz.timezone(event.device_id.timezone or "UTC")
            source_datetime = timezone.localize(
                local_datetime, is_dst=None,
            ).astimezone(pytz.UTC).replace(tzinfo=None)
            source_kind = event.device_id._adapter().map_punch_state(
                columns[punch_column].strip()
            )
            return source_pin, source_datetime, source_kind
        except (ValueError, pytz.UnknownTimeZoneError, pytz.AmbiguousTimeError, pytz.NonExistentTimeError):
            return False

    @api.depends(
        "event_datetime", "original_event_datetime", "employee_id",
        "original_employee_id", "device_employee_id", "original_device_employee_id",
        "device_user_id", "manual_punch_state", "punch_state", "raw_line",
        "log_id.request_type", "device_id.timezone", "device_id.punch_state_column",
    )
    def _compute_timeline_is_edited(self):
        raw_values_by_event = {
            event.id: self._timeline_raw_log_values(event)
            for event in self
        }
        raw_keys = {
            (event.device_id.id, raw_values_by_event[event.id][0])
            for event in self
            if raw_values_by_event[event.id]
        }
        cards_by_key = {}
        if raw_keys:
            cards = self.env["mdl.attendance.device.employee"].sudo().search([
                ("device_id", "in", list({key[0] for key in raw_keys})),
                ("device_user_id", "in", list({key[1] for key in raw_keys})),
            ])
            cards_by_key = {
                (card.device_id.id, card.device_user_id): card
                for card in cards
            }
        for event in self:
            raw_values = raw_values_by_event[event.id]
            if raw_values:
                source_pin, source_datetime, source_kind = raw_values
                source_card = cards_by_key.get((event.device_id.id, source_pin))
                source_employee = source_card.employee_id if source_card else event.original_employee_id
                card_changed = bool(
                    (source_card and event.device_employee_id != source_card)
                    or (
                        not source_card
                        and (event.device_user_id or event.device_employee_id.device_user_id)
                        != source_pin
                    )
                )
            else:
                source_datetime = event.original_event_datetime
                source_kind = event.punch_state
                source_card = event.original_device_employee_id
                source_employee = event.original_employee_id
                # MANUAL/import logs do not always contain a parseable ATTLOG line.
                # Their immutable device PIN still identifies the source card without
                # relying on a relational baseline introduced after the records existed.
                source_pin = event.device_user_id
                current_pin = event.device_employee_id.device_user_id
                card_changed = bool(source_pin and current_pin != source_pin)
            event.timeline_is_edited = bool(
                event.event_datetime != source_datetime
                or (event.manual_punch_state or event.punch_state) != source_kind
                or event.employee_id != source_employee
                or card_changed
            )

    def _clear_manual_timeline_pairs(self):
        if not self:
            return
        Event = self.env["mdl.attendance.device.event"].sudo()
        linked_events = Event.search([
            "|",
            ("id", "in", self.ids),
            ("timeline_pair_event_id", "in", self.ids),
        ])
        linked_events.filtered(
            lambda event: event.timeline_pair_event_id or event.timeline_pair_attendance_id
        ).write({"timeline_pair_event_id": False, "timeline_pair_attendance_id": False})
        self.timeline_blocked_in_event_ids = [(5, 0, 0)]
        self.timeline_blocked_attendance_ids = [(5, 0, 0)]
        Event.search([("timeline_blocked_in_event_ids", "in", self.ids)]).write({
            "timeline_blocked_in_event_ids": [(3, event_id) for event_id in self.ids],
        })

    def _drop_invalid_manual_timeline_pairs(self):
        """Keep edited manual pairs unless their time order/duration became invalid."""
        if not self:
            return
        Event = self.env["mdl.attendance.device.event"].sudo()
        out_events = self.filtered(
            lambda event: event.timeline_pair_event_id or event.timeline_pair_attendance_id
        ) | Event.search([("timeline_pair_event_id", "in", self.ids)])
        for out_event in out_events:
            out_employee = out_event.employee_id or out_event.device_employee_id.employee_id
            if out_event.timeline_pair_event_id:
                in_event = out_event.timeline_pair_event_id
                in_employee = in_event.employee_id or in_event.device_employee_id.employee_id
                valid = (
                    (in_event.manual_punch_state or in_event.punch_state) == "in"
                    and (out_event.manual_punch_state or out_event.punch_state) == "out"
                    and in_employee == out_employee
                    and in_event.event_datetime < out_event.event_datetime
                    and out_event.event_datetime - in_event.event_datetime <= timedelta(days=1)
                )
                if not valid:
                    out_event.write({
                        "timeline_pair_event_id": False,
                        "timeline_pair_attendance_id": False,
                        "timeline_blocked_in_event_ids": [(4, in_event.id)],
                    })
                continue

            attendance = out_event.timeline_pair_attendance_id
            valid = (
                attendance
                and not attendance.check_out
                and attendance.employee_id == out_employee
                and (out_event.manual_punch_state or out_event.punch_state) == "out"
                and attendance.check_in < out_event.event_datetime
                and out_event.event_datetime - attendance.check_in <= timedelta(days=1)
            )
            if not valid:
                values = {
                    "timeline_pair_event_id": False,
                    "timeline_pair_attendance_id": False,
                }
                if attendance:
                    values["timeline_blocked_attendance_ids"] = [(4, attendance.id)]
                out_event.write(values)

    def _sync_processed_manual_edit(self, previous_values):
        """Keep a processed event and its hr.attendance atomically consistent."""
        self.ensure_one()
        attendance = self.attendance_id.sudo().exists()
        if not attendance:
            raise UserError(_(
                "לא ניתן לערוך את האירוע כי רשומת הנוכחות המקושרת אינה קיימת."
            ))

        previous_kind = previous_values["kind"]
        effective_kind = self.manual_punch_state or self.punch_state
        if effective_kind != previous_kind:
            raise UserError(_(
                "לא ניתן לשנות את סוג האירוע שכבר נמצא בנוכחות. "
                "שינוי כזה ישאיר את רשומת הנוכחות ללא כניסה או ללא יציאה."
            ))

        employee = self.employee_id or self.device_employee_id.employee_id
        if not employee:
            raise UserError(_("יש לקשר את אירוע הנוכחות לעובד לפני השמירה."))

        check_in = self.event_datetime if effective_kind == "in" else attendance.check_in
        check_out = self.event_datetime if effective_kind == "out" else attendance.check_out
        if not check_in:
            raise UserError(_("לא ניתן לשמור נוכחות ללא שעת כניסה."))

        block_reason = self._timeline_block_reason(
            employee,
            check_in,
            check_out,
            exclude_attendance=attendance,
            enforce_max_duration=False,
        )
        if block_reason:
            raise UserError(_(
                "לא ניתן לשמור את השינוי באירוע הנוכחות: %(reason)s",
                reason=block_reason,
            ))

        attendance_values = {"employee_id": employee.id, "check_in": check_in}
        if attendance.check_out or effective_kind == "out":
            attendance_values["check_out"] = check_out
        try:
            attendance.write(attendance_values)
        except (UserError, ValidationError) as error:
            raise UserError(_(
                "לא ניתן לשמור את השינוי באירוע הנוכחות: %(reason)s",
                reason=str(error),
            )) from error

        if employee != previous_values["employee"]:
            sibling_events = self.sudo().search([
                ("attendance_id", "=", attendance.id),
                ("processing_state", "=", "processed"),
                ("id", "!=", self.id),
            ])
            sibling_events.with_context(attendance_event_system_write=True).write({
                "employee_id": employee.id,
            })

    def write(self, vals):
        if self.env.context.get("attendance_event_edit_in_progress"):
            return super().write(vals)

        editable_fields = {
            "employee_id", "event_datetime", "manual_punch_state", "effective_punch_state",
        }
        manually_edited = (
            editable_fields.intersection(vals)
            and not self.env.context.get("attendance_event_system_write")
        )
        previous_employee_ids = set()
        previous_attendance_ids = set()
        if manually_edited:
            blocked = self.filtered(lambda event: event.processing_state == "ignored")
            if blocked:
                raise UserError(_("לא ניתן לערוך אירוע שהוגדר כהתעלמות."))
            previous_employee_ids = {
                employee.id for employee in self.mapped("employee_id") if employee
            }
            previous_attendance_ids = set(self.mapped("attendance_id").ids)
            self._clear_manual_timeline_pairs()
            vals = dict(vals)
            vals.update({
                "processing_state": "not_applied",
                "processing_message": "Attendance event edited manually",
                "conflict_action_failed": False,
                "conflict_action_error": False,
            })
        result = super().write(vals)
        if (
            self.env.context.get("attendance_event_system_write")
            and "employee_id" in vals
        ):
            missing_employee_baseline = self.filtered(
                lambda event: not event.original_employee_id and event.employee_id
            )
            if missing_employee_baseline:
                super(
                    AttendanceDeviceEvent,
                    missing_employee_baseline.with_context(attendance_event_edit_in_progress=True),
                ).write({"original_employee_id": vals["employee_id"]})
        if manually_edited:
            current_employee_ids = {
                employee.id for employee in self.mapped("employee_id") if employee
            }
            old_only_ids = previous_employee_ids - current_employee_ids
            if old_only_ids:
                self._timeline_reconcile_employee_ids(
                    old_only_ids, force_attendance_ids=previous_attendance_ids,
                )
            self._timeline_reconcile_employee_ids(
                current_employee_ids,
                force_attendance_ids=previous_attendance_ids,
            )
        return result

    @api.depends("processing_state", "processing_message", "effective_punch_state", "conflict_action_error")
    def _compute_conflict_reason(self):
        for event in self:
            message = event.conflict_action_error or event.processing_message or ""
            normalized = message.lower()
            if event.conflict_action_error:
                reason = event.conflict_action_error
            elif event.processing_state == "waiting_employee_link" or "not linked to an employee" in normalized:
                reason = "כרטיס השעון אינו מקושר לעובד"
            elif "already has an open attendance" in normalized or "חסרה יציאה" in message:
                reason = "חסרה יציאה"
            elif "no open attendance found" in normalized or "חסרה כניסה" in message:
                reason = "חסרה כניסה"
            elif "24" in normalized and ("hour" in normalized or "שעות" in normalized):
                reason = "האירוע חורג ממגבלת 24 שעות"
            elif "overlap" in normalized or "חפיפ" in normalized:
                reason = "האירוע חופף לרשומת נוכחות קיימת"
            elif event.processing_state == "error":
                reason = "שגיאה בעיבוד אירוע הנוכחות"
            else:
                reason = "האירוע נחסם על ידי כללי הנוכחות של Odoo"
            event.conflict_reason = reason

    def action_process(self):
        from ..services.attendance_processor import AttendanceProcessor
        AttendanceProcessor(self.env).process(self)
        return True

    def action_dismiss_conflict(self):
        """Hide a conflict without changing the source event or attendance data."""
        self.sudo().write({"conflict_dismissed": True})
        return {"type": "ir.actions.client", "tag": "reload"}
