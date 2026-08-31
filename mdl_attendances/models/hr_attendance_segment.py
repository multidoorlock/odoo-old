from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrAttendanceSegment(models.Model):
    _name = "hr.attendance.segment"
    _description = "Attendance Segment"
    _order = "time_start, id"
    _minimum_duration = timedelta(minutes=1)

    attendance_id = fields.Many2one(
        "hr.attendance", required=True, ondelete="cascade", index=True)
    employee_id = fields.Many2one(related="attendance_id.employee_id", store=True, index=True)
    company_id = fields.Many2one(related="employee_id.company_id", store=True, index=True)
    time_start = fields.Datetime(required=True, index=True)
    time_stop = fields.Datetime(required=True, index=True)
    duration = fields.Float(compute="_compute_duration", store=True)
    is_work = fields.Boolean(string="Work", default=True, required=True)
    segment_type = fields.Selection(
        [("work", "Work"), ("non_work", "Non-Work")],
        string="Segment Type", compute="_compute_segment_type", inverse="_inverse_segment_type",
        store=True, readonly=False,
    )
    rule_id = fields.Many2one("hr.attendance.segment.rule", ondelete="set null", readonly=True)
    name = fields.Char()
    manual_override = fields.Boolean(readonly=True)
    width_percent = fields.Float(compute="_compute_width_percent")
    is_first = fields.Boolean(compute="_compute_edge_flags")
    is_last = fields.Boolean(compute="_compute_edge_flags")
    hover_label = fields.Char(compute="_compute_hover_label")

    @api.depends("is_work")
    def _compute_segment_type(self):
        for segment in self:
            segment.segment_type = "work" if segment.is_work else "non_work"

    def _inverse_segment_type(self):
        for segment in self:
            segment.is_work = segment.segment_type == "work"

    @api.depends("time_start", "time_stop", "is_work", "employee_id")
    def _compute_hover_label(self):
        for segment in self:
            if not segment.time_start or not segment.time_stop or not segment.employee_id:
                segment.hover_label = False
                continue
            start = fields.Datetime.context_timestamp(segment, segment.time_start).strftime("%H:%M")
            stop = fields.Datetime.context_timestamp(segment, segment.time_stop).strftime("%H:%M")
            # Keep the complete range left-to-right even inside Odoo's RTL UI.
            # LRI/PDI are stronger than LRM and prevent the two times swapping sides.
            segment.hover_label = "\u2066%s - %s\u2069" % (start, stop)

    @api.depends("time_start", "time_stop")
    def _compute_duration(self):
        for segment in self:
            segment.duration = max(
                (segment.time_stop - segment.time_start).total_seconds() / 3600.0, 0.0
            ) if segment.time_start and segment.time_stop else 0.0

    @api.depends("duration", "attendance_id.check_in", "attendance_id.check_out")
    def _compute_width_percent(self):
        for segment in self:
            attendance = segment.attendance_id
            total = ((attendance.check_out - attendance.check_in).total_seconds() / 3600.0
                     if attendance.check_in and attendance.check_out else 0.0)
            segment.width_percent = 100.0 * segment.duration / total if total else 100.0

    @api.depends("attendance_id.segment_ids.time_start", "attendance_id.segment_ids.time_stop")
    def _compute_edge_flags(self):
        for segment in self:
            ordered = segment.attendance_id.segment_ids.sorted("time_start")
            segment.is_first = bool(ordered and ordered[0] == segment)
            segment.is_last = bool(ordered and ordered[-1] == segment)

    @api.constrains("time_start", "time_stop")
    def _check_positive_duration(self):
        for segment in self:
            if segment.time_start and segment.time_stop and segment.time_start >= segment.time_stop:
                raise ValidationError(_("A segment must have a positive duration."))

    def write(self, vals):
        if (self.env.context.get("segment_boundary_sync")
                or self.env.context.get("segment_normalization")
                or self.env.context.get("segment_generation")):
            return super().write(vals)
        raise ValidationError(_("Attendance segments are read-only and are generated from segmentation rules."))

    def unlink(self):
        if (self.env.context.get("segment_boundary_sync")
                or self.env.context.get("segment_normalization")
                or self.env.context.get("segment_generation")):
            return super().unlink()
        raise ValidationError(_("Attendance segments cannot be deleted manually. Regenerate them from the rules."))
