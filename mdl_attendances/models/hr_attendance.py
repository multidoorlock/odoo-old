from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz
from dateutil.rrule import rrule, DAILY

from odoo import api, fields, models, _
from odoo.fields import Domain
from odoo.exceptions import ValidationError
from odoo.tools.intervals import Intervals


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    segment_ids = fields.One2many(
        "hr.attendance.segment", "attendance_id", string="Attendance Segments", copy=False)
    presence_hours = fields.Float(
        string="Presence Hours", compute="_compute_presence_hours", store=True, readonly=True)
    mdl_pending_overtime_hours = fields.Float(
        string='Hours to Approve', compute='_compute_mdl_pending_overtime_hours',
        store=True, readonly=True, aggregator='sum',
        help='Approval hours from overtime lines that are still awaiting approval, '
             'including the whole-shift rounding policy.',
    )
    timeline_start_label = fields.Char(compute="_compute_timeline_labels")
    timeline_stop_label = fields.Char(compute="_compute_timeline_labels")

    @api.depends('employee_id', 'check_in', 'check_out')
    def _compute_mdl_pending_overtime_hours(self):
        # Native links are computed by employee and check-in, not a stored
        # inverse relation. Query them freshly after line creation/removal.
        pending = self._linked_overtimes().filtered(lambda line: line.status == 'to_approve')
        by_attendance = pending.grouped(lambda line: (line.employee_id.id, line.time_start))
        for attendance in self:
            lines = by_attendance.get((attendance.employee_id.id, attendance.check_in), pending.browse())
            attendance.mdl_pending_overtime_hours = sum(lines.mapped('manual_duration'))

    def _mdl_whole_shift_attendance_domain(self, attendance_domain):
        """Include every source punch when an overnight workday is affected."""
        domains = [attendance_domain]
        seen = set()
        for attendance in (self.exists() | self.search(attendance_domain)).filtered('check_out'):
            start = attendance._get_localized_times()[0]
            version = attendance.employee_id.sudo()._get_version(start)
            if not any(rule.base_off == 'quantity' and rule.quantity_period == 'shift'
                       for rule in version.ruleset_id.rule_ids):
                continue
            key = (attendance.employee_id.id, start.date())
            if key in seen:
                continue
            seen.add(key)
            tz = pytz.timezone(version._get_tz())
            lower = tz.localize(datetime.combine(start.date(), time.min)).astimezone(pytz.utc).replace(tzinfo=None)
            upper = tz.localize(datetime.combine(start.date() + timedelta(days=1), time.min)).astimezone(pytz.utc).replace(tzinfo=None)
            domains.append(Domain.AND([
                Domain('employee_id', '=', attendance.employee_id.id),
                Domain('check_in', '>=', lower), Domain('check_in', '<', upper),
            ]))
        return Domain.OR(domains)

    def _update_overtime(self, attendance_domain=None):
        base_domain = attendance_domain or self._get_overtimes_to_update_domain()
        expanded_domain = self._mdl_whole_shift_attendance_domain(base_domain)
        affected_attendances = (self.exists() | self.search(expanded_domain)).filtered('check_out')
        # Odoo 19 uses the same employee/date domain for attendance and
        # overtime lines.  The whole-shift domain also contains check_in,
        # which is not a field on overtime lines, so derive a shared domain
        # from the affected attendances while retaining the original domain
        # (needed when the last attendance of a day was deleted).
        overtime_domain = Domain.OR([
            base_domain,
            affected_attendances._get_overtimes_to_update_domain(),
        ])
        line_model = self.env['hr.attendance.overtime.line']
        previous = line_model.search(overtime_domain)
        restore_default = set()
        for key, lines in previous.grouped(lambda line: (line.employee_id.id, line.date)).items():
            if (lines.company_id.attendance_overtime_validation != 'by_manager'
                    and any(line.mdl_auto_approval_hours > 0 for line in lines)
                    and all(line.status == 'approved' and not line._mdl_has_manual_duration_override()
                            for line in lines)):
                restore_default.add(key)
        result = super()._update_overtime(attendance_domain=overtime_domain)
        if restore_default:
            # Native regeneration sees rounded manual_duration != raw duration
            # as a human edit. Restore only the automatic company's default;
            # manager decisions and genuine manual changes keep native behavior.
            line_model.search(overtime_domain).filtered(
                lambda line: (line.employee_id.id, line.date) in restore_default
                and line.company_id.attendance_overtime_validation != 'by_manager'
                and line.mdl_auto_approval_hours > 0
                and any(line.rule_ids.mapped('mdl_shift_rounding_threshold_minutes'))
                and not line._mdl_has_manual_duration_override()
            ).write({'status': 'approved'})
        affected_attendances._mdl_sync_shift_overtime_marks()
        return result

    def _mdl_sync_shift_overtime_marks(self):
        """Refresh only the visual overtime tail of existing effective work.

        This callback runs after attendance overtime regeneration, never after
        direct overtime-line repair. Keep every existing work/non-work boundary
        and its manual/source metadata; only introduce an overtime split when
        the new tail starts inside a work segment.
        """
        Segment = self.env['hr.attendance.segment'].with_context(
            segment_generation=True, segment_boundary_sync=True)
        for attendance in self.filtered('check_out'):
            version = attendance.employee_id.sudo()._get_version(attendance._get_localized_times()[0])
            if not any(rule.base_off == 'quantity' and rule.quantity_period == 'shift'
                       for rule in version.ruleset_id.rule_ids):
                continue
            segments = attendance.segment_ids.sorted('time_start')
            if (not segments or segments[0].time_start != attendance.check_in
                    or segments[-1].time_stop != attendance.check_out):
                # During a native attendance boundary write, the segmentation
                # layer has not yet rebuilt its partition. Its next callback
                # will reach this method with the new complete partition.
                continue
            intervals = [{
                'start': segment.time_start, 'stop': segment.time_stop,
                'is_work': segment.is_work, 'is_overtime': False,
                'rule_id': segment.rule_id.id, 'name': segment.name,
                'source_segment': segment,
            } for segment in segments]
            raw_hours = sum(attendance._linked_overtimes().mapped('duration'))
            desired = attendance._apply_native_overtime(intervals, max(raw_hours, 0.0))
            by_source = defaultdict(list)
            for item in desired:
                by_source[item['source_segment']].append(item)
            for source, items in by_source.items():
                original_name = source.name
                for index, item in enumerate(items):
                    values = {
                        'time_start': item['start'], 'time_stop': item['stop'],
                        'is_overtime': bool(item.get('is_overtime')),
                    }
                    if index:
                        Segment.create({
                            **values, 'attendance_id': attendance.id,
                            'is_work': source.is_work, 'rule_id': source.rule_id.id,
                            'manual_override': source.manual_override,
                            'name': original_name,
                        })
                    else:
                        changes = {name: value for name, value in values.items() if source[name] != value}
                        if changes:
                            source.with_context(segment_generation=True, segment_boundary_sync=True).write(changes)
            attendance._validate_segment_coverage()

    @api.depends("check_in", "check_out")
    def _compute_presence_hours(self):
        for attendance in self:
            attendance.presence_hours = (
                (attendance.check_out - attendance.check_in).total_seconds() / 3600.0
                if attendance.check_in and attendance.check_out else 0.0
            )

    @api.depends("check_in", "check_out", "employee_id")
    def _compute_timeline_labels(self):
        for attendance in self:
            if not attendance.check_in or not attendance.employee_id:
                attendance.timeline_start_label = False
                attendance.timeline_stop_label = False
                continue
            # Match the datetime widget in the attendance form: Odoo displays
            # datetimes in the current user's timezone, not the employee calendar timezone.
            local_start = fields.Datetime.context_timestamp(attendance, attendance.check_in)
            attendance.timeline_start_label = local_start.strftime("%H:%M")
            if attendance.check_out:
                local_stop = fields.Datetime.context_timestamp(attendance, attendance.check_out)
                attendance.timeline_stop_label = local_stop.strftime("%H:%M")
            else:
                attendance.timeline_stop_label = False

    @api.depends(
        "check_in", "check_out", "employee_id",
        "segment_ids.time_start", "segment_ids.time_stop", "segment_ids.is_work",
    )
    def _compute_worked_hours(self):
        segmented = self.filtered(lambda attendance: attendance.check_out and attendance.segment_ids)
        for attendance in segmented:
            # Always derive the value from the canonical boundaries.  Do not sum
            # the stored duration cache: adjacent boundary edits update multiple
            # records in one transaction and an old cached duration must never be
            # able to inflate Worked Hours.
            attendance.worked_hours = sum(
                (segment.time_stop - segment.time_start).total_seconds() / 3600.0
                for segment in attendance.segment_ids.filtered("is_work")
            )
        super(HrAttendance, self - segmented)._compute_worked_hours()

    def _segment_ruleset(self):
        self.ensure_one()
        if not self.employee_id or not self.date:
            return self.env["hr.attendance.segment.ruleset"]
        return self.employee_id.sudo()._get_version(self.date).segment_ruleset_id

    def _effective_work_intervals(self, localized=False):
        self.ensure_one()
        values = []
        for segment in self.segment_ids.filtered("is_work").sorted("time_start"):
            start, stop = segment.time_start, segment.time_stop
            if localized:
                tz = pytz.timezone(self.employee_id.sudo()._get_version(self.date)._get_tz())
                start = pytz.utc.localize(start).astimezone(tz).replace(tzinfo=None)
                stop = pytz.utc.localize(stop).astimezone(tz).replace(tzinfo=None)
            values.append((start, stop, self))
        if not values and not self.segment_ids and self.check_in and self.check_out:
            start, stop = self.check_in, self.check_out
            if localized:
                start, stop = self._get_localized_times()
            values.append((start, stop, self))
        return values

    def _apply_interval(self, intervals, start, stop, rule):
        if start >= stop:
            return intervals
        result = []
        for item in intervals:
            item_start, item_stop = item["start"], item["stop"]
            if stop <= item_start or start >= item_stop:
                result.append(item)
                continue
            if item_start < start:
                result.append({**item, "stop": start})
            result.append({
                "start": max(item_start, start),
                "stop": min(item_stop, stop),
                "is_work": rule.is_work,
                # Segmentation rules decide only work/non-work. Overtime is
                # applied later and comes exclusively from native Odoo data.
                "is_overtime": False,
                "rule_id": rule.id,
                "name": rule.name,
            })
            if stop < item_stop:
                result.append({**item, "start": stop})
        return [item for item in result if item["start"] < item["stop"]]

    def _apply_native_overtime(self, intervals, overtime_hours):
        """Mark the final effective-work portion as Odoo overtime."""
        already_marked = sum(
            (item["stop"] - item["start"]).total_seconds() / 3600.0
            for item in intervals
            if item["is_work"] and item.get("is_overtime")
        )
        remaining = max((overtime_hours or 0.0) - already_marked, 0.0)
        if not remaining:
            return intervals
        result = list(intervals)
        for index in range(len(result) - 1, -1, -1):
            item = result[index]
            if not item["is_work"] or item.get("is_overtime"):
                continue
            duration = (item["stop"] - item["start"]).total_seconds() / 3600.0
            overtime_duration = min(duration, remaining)
            overtime_start = item["stop"] - timedelta(hours=overtime_duration)
            overtime_item = {
                **item,
                "start": overtime_start,
                "is_work": True,
                "is_overtime": True,
                "rule_id": False,
                "name": _("Overtime"),
            }
            if overtime_start > item["start"]:
                result[index:index + 1] = [
                    {**item, "stop": overtime_start},
                    overtime_item,
                ]
            else:
                result[index] = overtime_item
            remaining -= overtime_duration
            if remaining <= 1e-9:
                break
        return result

    def _timing_rule_windows(self, rule):
        self.ensure_one()
        rule_tz = rule._timing_timezone(self)
        local_start = pytz.utc.localize(self.check_in).astimezone(rule_tz).replace(tzinfo=None)
        local_stop = pytz.utc.localize(self.check_out).astimezone(rule_tz).replace(tzinfo=None)
        windows = []
        company = rule.company_id or self.employee_id.company_id
        calendar = rule.resource_calendar_id or company.resource_calendar_id

        # One attendance represents one business shift.  For an overnight
        # attendance the early-morning window therefore inherits the work-day
        # condition of the date on which the attendance started.
        if rule.timing_type in ("work_days", "non_work_days"):
            business_date = local_start.date()
            day_start = rule_tz.localize(datetime.combine(business_date, time.min))
            day_stop = rule_tz.localize(datetime.combine(business_date, time.max))
            unusual_days = calendar._get_unusual_days(
                day_start, day_stop, company_id=company)
            is_non_work_day = unusual_days.get(
                business_date.strftime("%Y-%m-%d"), False)
            if rule.timing_type == "work_days" and is_non_work_day:
                return windows
            if rule.timing_type == "non_work_days" and not is_non_work_day:
                return windows

        for day in rrule(DAILY, dtstart=local_start.date(), until=local_stop.date()):
            local_date = day.date()
            if rule.timing_type in ("work_days", "non_work_days"):
                windows.append(rule._local_window_utc(self, local_date))
                continue
            if rule.timing_type == "leave":
                version = self.employee_id.sudo()._get_version(local_date)
                tz = pytz.timezone(version._get_tz())
                day_start = tz.localize(datetime.combine(local_date, time.min))
                day_stop = tz.localize(datetime.combine(local_date, time.max))
                leave_intervals = version.resource_calendar_id._leave_intervals_batch(
                    day_start, day_stop, self.employee_id.resource_id, tz=tz
                )[self.employee_id.resource_id.id]
                windows.extend([
                    (start.astimezone(pytz.utc).replace(tzinfo=None),
                     stop.astimezone(pytz.utc).replace(tzinfo=None))
                    for start, stop, _records in leave_intervals
                ])
                continue
            calendar = rule.resource_calendar_id
            resource = self.employee_id.resource_id
            tz = pytz.timezone(calendar.tz)
            day_start = tz.localize(datetime.combine(local_date, time.min))
            day_stop = tz.localize(datetime.combine(local_date, time.max))
            scheduled = calendar._attendance_intervals_batch(
                day_start, day_stop, resource, tz=tz)[resource.id]
            cursor = max(self.check_in, day_start.astimezone(pytz.utc).replace(tzinfo=None))
            attendance_stop = min(self.check_out, day_stop.astimezone(pytz.utc).replace(tzinfo=None))
            for scheduled_start, scheduled_stop, _records in scheduled:
                scheduled_start = scheduled_start.astimezone(pytz.utc).replace(tzinfo=None)
                scheduled_stop = scheduled_stop.astimezone(pytz.utc).replace(tzinfo=None)
                if cursor < scheduled_start:
                    windows.append((cursor, min(scheduled_start, attendance_stop)))
                cursor = max(cursor, scheduled_stop)
            if cursor < attendance_stop:
                windows.append((cursor, attendance_stop))
        return windows

    def _generate_segments(self):
        Segment = self.env["hr.attendance.segment"]
        for attendance in self:
            attendance.segment_ids.with_context(segment_boundary_sync=True).unlink()
            if not attendance.check_in or not attendance.check_out:
                continue
            # Odoo queues these stored fields for recomputation after editing
            # attendance boundaries. Read a fresh value before constructing
            # the visual segments, otherwise an old month-long value can leak
            # into the regenerated timeline.
            attendance._compute_overtime_hours()
            intervals = [{
                "start": attendance.check_in,
                "stop": attendance.check_out,
                "is_work": True,
                "is_overtime": False,
                "rule_id": False,
                "name": _("Work"),
            }]
            ruleset = attendance._segment_ruleset()
            for rule in ruleset.rule_ids.sorted(lambda record: (record.sequence, record.id)):
                if rule.base_off == "timing":
                    for start, stop in attendance._timing_rule_windows(rule):
                        clipped_start = max(start, attendance.check_in)
                        clipped_stop = min(stop, attendance.check_out)
                        overlap_hours = max(
                            (clipped_stop - clipped_start).total_seconds() / 3600.0,
                            0.0,
                        )
                        if not overlap_hours:
                            continue
                        if not rule.is_work:
                            # Employee tolerance is measured backwards from the
                            # end of the timing window. A late check-in inside
                            # that grace period remains work; reaching the full
                            # tolerance still activates the non-work window.
                            if (rule.employee_tolerance
                                    and start <= attendance.check_in < stop):
                                seconds_to_stop = (
                                    stop - attendance.check_in).total_seconds()
                                if seconds_to_stop < round(
                                        rule.employee_tolerance * 3600):
                                    continue

                            if attendance.check_out > stop:
                                # Employer tolerance extends non-work through a
                                # near check-out. Once the grace period is
                                # exceeded, the original timing stop is kept.
                                seconds_after_stop = (
                                    attendance.check_out - stop).total_seconds()
                                if (rule.employer_tolerance
                                        and seconds_after_stop <= round(
                                            rule.employer_tolerance * 3600)):
                                    clipped_stop = attendance.check_out
                            elif (rule.employer_tolerance
                                  and overlap_hours <= rule.employer_tolerance):
                                # A very short attendance ending inside the
                                # window (for example at 01:45) did not reach a
                                # meaningful non-work period.
                                continue
                        elif overlap_hours <= rule.employer_tolerance:
                            continue
                        intervals = attendance._apply_interval(
                            intervals, clipped_start, clipped_stop, rule)
                else:
                    work_intervals = [item for item in intervals if item["is_work"]]
                    expected = rule.expected_hours
                    if rule.expected_hours_from_contract:
                        expected = rule._expected_hours_for(attendance)
                    excess = sum((item["stop"] - item["start"]).total_seconds() / 3600 for item in work_intervals) - expected
                    if excess <= rule.employer_tolerance:
                        continue
                    # Once the employer threshold is crossed, preserve the
                    # employee-favour tolerance as effective work time.
                    remaining = max(excess - rule.employee_tolerance, 0.0)
                    for item in reversed(work_intervals):
                        duration = (item["stop"] - item["start"]).total_seconds() / 3600
                        cut_start = item["stop"] - timedelta(hours=min(duration, remaining))
                        intervals = attendance._apply_interval(intervals, cut_start, item["stop"], rule)
                        remaining -= min(duration, remaining)
                        if remaining <= 0:
                            break
            intervals = attendance._apply_native_overtime(
                intervals, attendance.overtime_hours,
            )
            Segment.create([{
                "attendance_id": attendance.id,
                "time_start": item["start"],
                "time_stop": item["stop"],
                "is_work": item["is_work"],
                "is_overtime": item.get("is_overtime", False),
                "rule_id": item["rule_id"],
                "name": item["name"],
            } for item in intervals])
            attendance._validate_segment_coverage()

    def _validate_segment_coverage(self):
        for attendance in self.filtered(lambda record: record.check_out):
            segments = attendance.segment_ids.sorted("time_start")
            if not segments:
                raise ValidationError(_("A closed attendance must have at least one segment."))
            if segments[0].time_start != attendance.check_in or segments[-1].time_stop != attendance.check_out:
                raise ValidationError(_("Segments must cover the attendance from Check In through Check Out."))
            for previous, current in zip(segments, segments[1:]):
                if previous.time_stop != current.time_start:
                    raise ValidationError(_("Attendance segments cannot contain gaps or overlaps."))
            covered_seconds = sum(
                (segment.time_stop - segment.time_start).total_seconds()
                for segment in segments
            )
            presence_seconds = (attendance.check_out - attendance.check_in).total_seconds()
            if covered_seconds != presence_seconds:
                raise ValidationError(_("Segment durations must equal the attendance presence time."))

    def _normalize_segments(self):
        """Merge equal neighbours and enforce a gap-free canonical partition."""
        for attendance in self.filtered(lambda record: record.check_out):
            attendance._validate_segment_coverage()
            while True:
                ordered = attendance.segment_ids.sorted("time_start")
                pair = next((
                    (left, right)
                    for left, right in zip(ordered, ordered[1:])
                    if (left.is_work, left.is_overtime) == (right.is_work, right.is_overtime)
                ), None)
                if not pair:
                    break
                left, right = pair
                left.with_context(segment_boundary_sync=True).write({
                    "time_stop": right.time_stop,
                    "manual_override": left.manual_override or right.manual_override,
                    "rule_id": left.rule_id.id if left.rule_id == right.rule_id else False,
                    "name": left.name if left.name == right.name else (_("Work") if left.is_work else _("Non-Work")),
                })
                right.with_context(segment_normalization=True).unlink()
            attendance._validate_segment_coverage()

    def _segments_changed(self):
        if self.env.context.get("segment_generation"):
            return
        self._validate_segment_coverage()
        # Compute synchronously so the parent attendance cannot retain a stale
        # value after closing the segment popup.
        self._compute_worked_hours()
        self.flush_recordset(["worked_hours"])
        self.invalidate_recordset(["worked_hours"])
        self._update_overtime()
        self._refresh_displayed_overtime_fields()

    def _refresh_displayed_overtime_fields(self):
        """Refresh stored overtime values before returning the edited form."""
        closed = self.filtered("check_out")
        if not closed:
            return
        closed._compute_overtime_hours()
        closed._compute_validated_overtime_hours()
        closed._compute_overtime_status()
        closed.flush_recordset([
            "overtime_hours", "validated_overtime_hours", "overtime_status",
        ])

    def action_regenerate_segments(self):
        self.with_context(segment_generation=True)._generate_segments()
        self.env.add_to_compute(self._fields["worked_hours"], self)
        self.flush_recordset(["worked_hours"])
        self._update_overtime()
        self._refresh_displayed_overtime_fields()
        return {"type": "ir.actions.client", "tag": "reload"}

    @api.model_create_multi
    def create(self, vals_list):
        attendances = super().create(vals_list)
        attendances.filtered("check_out").with_context(segment_generation=True)._generate_segments()
        attendances._segments_changed()
        return attendances

    def write(self, vals):
        boundary_change = any(field_name in vals for field_name in ("check_in", "check_out", "employee_id"))
        result = super().write(vals)
        if boundary_change and not self.env.context.get("segment_generation"):
            self.with_context(segment_generation=True)._generate_segments()
            self._segments_changed()
        return result

    def _get_attendance_by_periods_by_employee(self):
        by_day = defaultdict(lambda: defaultdict(lambda: Intervals([], keep_distinct=True)))
        by_week = defaultdict(lambda: defaultdict(lambda: Intervals([], keep_distinct=True)))
        for attendance in self.sorted("check_in"):
            employee = attendance.employee_id
            for start, stop, record in attendance._effective_work_intervals(localized=True):
                for day in rrule(dtstart=start.date(), until=stop.date(), freq=DAILY):
                    week_date = day.date() + timedelta(days=6 - day.weekday())
                    day_interval = Intervals([(
                        datetime.combine(day.date(), time.min), datetime.combine(day.date(), time.max), record)])
                    week_interval = Intervals([(
                        datetime.combine(day.date(), time.min), datetime.combine(week_date, time.max), record)])
                    effective = Intervals([(start, stop, record)])
                    by_day[employee][day] |= effective & day_interval
                    by_week[employee][week_date] |= effective & week_interval
        return {"day": by_day, "week": by_week}
