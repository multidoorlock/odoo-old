from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrAttendanceSegmentRuleset(models.Model):
    _name = "hr.attendance.segment.ruleset"
    _description = "Attendance Segmentation Ruleset"
    _order = "name"

    name = fields.Char(required=True)
    description = fields.Html()
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    rule_ids = fields.One2many("hr.attendance.segment.rule", "ruleset_id", copy=True)
    active = fields.Boolean(default=True)

    def _attendances_to_regenerate(self):
        versions = self.env["hr.version"].search([("segment_ruleset_id", "in", self.ids)])
        if not versions:
            return self.env["hr.attendance"]
        return self.env["hr.attendance"].search([
            ("employee_id", "in", versions.employee_id.ids),
            ("check_out", "!=", False),
            ("date", ">=", min(versions.mapped("date_version"))),
        ])

    def action_regenerate_segments(self):
        attendances = self._attendances_to_regenerate()
        attendances.action_regenerate_segments()
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "title": _("Segments regenerated"),
            "message": _("%(count)s attendances were regenerated.", count=len(attendances)),
            "type": "success",
        }}


class HrAttendanceSegmentRule(models.Model):
    _name = "hr.attendance.segment.rule"
    _description = "Attendance Segmentation Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    description = fields.Html()
    sequence = fields.Integer(default=10)
    ruleset_id = fields.Many2one(
        "hr.attendance.segment.ruleset", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="ruleset_id.company_id", store=True)
    base_off = fields.Selection(
        [("quantity", "Quantity"), ("timing", "Timing")], required=True, default="timing")
    expected_hours_from_contract = fields.Boolean(default=True)
    expected_hours = fields.Float(string="Usual Work Hours")
    # Weekly aggregation is intentionally not exposed until it is calculated
    # across all attendances in the week (never per attendance).
    quantity_period = fields.Selection([("day", "Day")], default="day")
    employee_tolerance = fields.Float(
        help="For quantity rules, this many excess hours remain effective work time after the employer threshold is crossed. "
             "For non-work timing rules, this duration at the start of the matching interval remains effective work time.")
    employer_tolerance = fields.Float(
        help="For quantity rules, excess at or below this threshold is ignored. "
             "For timing rules, the rule is ignored when its overlap with the attendance "
             "is at or below this duration.")
    timing_type = fields.Selection([
        ("work_days", "On any working day"),
        ("non_work_days", "On any non-working day"),
        ("leave", "When employee is off"),
        ("schedule", "Outside of a specific schedule"),
    ], default="work_days")
    timing_start = fields.Float(string="From", default=0.0)
    timing_stop = fields.Float(string="To", default=24.0)
    resource_calendar_id = fields.Many2one(
        "resource.calendar", string="Schedule", domain=[("flexible_hours", "=", False)])
    is_work = fields.Boolean(string="Work", default=True)
    segment_type = fields.Selection(
        [("work", "Work"), ("non_work", "Non-Work")],
        string="Segment Type", compute="_compute_segment_type", inverse="_inverse_segment_type",
        store=True, readonly=False,
    )

    @api.depends("is_work")
    def _compute_segment_type(self):
        for rule in self:
            rule.segment_type = "work" if rule.is_work else "non_work"

    def _inverse_segment_type(self):
        for rule in self:
            rule.is_work = rule.segment_type == "work"

    _timing_start_valid = models.Constraint(
        "CHECK(0 <= timing_start AND timing_start < 24)", "Start must be an hour between 00:00 and 23:59.")
    _timing_stop_valid = models.Constraint(
        "CHECK(0 < timing_stop AND timing_stop <= 24)", "Stop must be an hour between 00:01 and 24:00.")

    @api.constrains("base_off", "expected_hours_from_contract", "expected_hours", "quantity_period")
    def _check_quantity(self):
        for rule in self:
            if rule.base_off == "quantity" and not rule.quantity_period:
                raise ValidationError(_("A quantity rule requires a period."))
            if rule.base_off == "quantity" and not rule.expected_hours_from_contract and rule.expected_hours <= 0:
                raise ValidationError(_("A quantity rule requires a positive usual work duration."))

    @api.constrains("employee_tolerance", "employer_tolerance")
    def _check_non_negative_tolerances(self):
        if any(rule.employee_tolerance < 0 or rule.employer_tolerance < 0 for rule in self):
            raise ValidationError(_("Tolerances cannot be negative."))

    @api.constrains("base_off", "timing_type", "resource_calendar_id")
    def _check_schedule(self):
        for rule in self:
            if rule.base_off == "timing" and rule.timing_type == "schedule" and not rule.resource_calendar_id:
                raise ValidationError(_("A schedule timing rule requires a schedule."))

    @api.constrains("ruleset_id", "base_off", "timing_type", "timing_start", "timing_stop",
                    "resource_calendar_id")
    def _check_conflicting_rules(self):
        def parts(rule):
            if rule.timing_start < rule.timing_stop:
                return [(rule.timing_start, rule.timing_stop)]
            return [(rule.timing_start, 24.0), (0.0, rule.timing_stop)]

        for rule in self.filtered(lambda item: item.base_off == "timing"):
            candidates = rule.ruleset_id.rule_ids.filtered(
                lambda other: other.id != rule.id
                and other.base_off == "timing"
                and other.timing_type == rule.timing_type
                and (rule.timing_type != "schedule"
                     or other.resource_calendar_id == rule.resource_calendar_id)
            )
            if rule.timing_type not in ("work_days", "non_work_days"):
                if candidates:
                    raise ValidationError(_("Two segmentation rules with the same timing condition cannot coexist."))
                continue
            if any(
                max(start_a, start_b) < min(stop_a, stop_b)
                for other in candidates
                for start_a, stop_a in parts(rule)
                for start_b, stop_b in parts(other)
            ):
                raise ValidationError(_("Timing segmentation rules in the same ruleset cannot overlap."))

    def _local_window_utc(self, attendance, local_date):
        self.ensure_one()
        tz = pytz.timezone(attendance.employee_id.sudo()._get_version(local_date)._get_tz())
        start = datetime.combine(local_date, time.min) + timedelta(hours=self.timing_start)
        stop = datetime.combine(local_date, time.min) + timedelta(hours=self.timing_stop)
        if stop <= start:
            stop += timedelta(days=1)
        return (
            tz.localize(start).astimezone(pytz.utc).replace(tzinfo=None),
            tz.localize(stop).astimezone(pytz.utc).replace(tzinfo=None),
        )

    def _expected_hours_for(self, attendance):
        self.ensure_one()
        if not self.expected_hours_from_contract:
            return self.expected_hours
        local_date = attendance.date
        if self.quantity_period == "week":
            date_start = local_date - timedelta(days=local_date.weekday())
            date_stop = date_start + timedelta(days=7)
        else:
            date_start = local_date
            date_stop = date_start + timedelta(days=1)
        tz = pytz.timezone(attendance.employee_id.sudo()._get_version(local_date)._get_tz())
        start = tz.localize(datetime.combine(date_start, time.min))
        stop = tz.localize(datetime.combine(date_stop, time.min))
        intervals = attendance.employee_id._employee_attendance_intervals(start, stop)
        return sum((interval_stop - interval_start).total_seconds() for interval_start, interval_stop, _record in intervals) / 3600.0
