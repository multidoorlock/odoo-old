from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.date_utils import sum_intervals
from odoo.tools.float_utils import float_compare
from odoo.tools.intervals import Intervals
from odoo.addons.hr_attendance.models.hr_attendance_overtime_rule import (
    _last_hours_as_intervals, _record_overlap_intervals,
)


class HrAttendanceOvertimeRule(models.Model):
    _inherit = "hr.attendance.overtime.rule"

    quantity_period = fields.Selection(
        selection_add=[('shift', 'Whole Shift / Workday')],
        ondelete={'shift': 'set default'},
        help='Whole Shift / Workday combines all effective work from attendances '
             'that start on the same local date, including work after midnight. '
             'Non-work segments are excluded. Daily and weekly rules keep their native behavior.',
    )
    mdl_shift_rounding_threshold_minutes = fields.Integer(
        string='Whole-shift Rounding Threshold (minutes)', default=0,
        help='Zero keeps exact overtime hours. Otherwise, round the whole workday '
             'to full payable hours, adding the next hour when the remaining '
             'minutes reach this threshold. Actual work intervals are unchanged.',
    )

    @api.onchange('base_off', 'quantity_period')
    def _onchange_mdl_shift_quantity(self):
        for rule in self:
            if rule.base_off == 'quantity' and rule.quantity_period == 'shift':
                rule.expected_hours_from_contract = False
            else:
                rule.mdl_shift_rounding_threshold_minutes = 0

    @api.constrains('base_off', 'quantity_period', 'ruleset_id', 'expected_hours_from_contract',
                    'mdl_shift_rounding_threshold_minutes')
    def _check_mdl_shift_quantity_configuration(self):
        for rule in self:
            threshold = rule.mdl_shift_rounding_threshold_minutes
            if not 0 <= threshold < 60 or (threshold and not (
                    rule.base_off == 'quantity' and rule.quantity_period == 'shift')):
                raise ValidationError(self.env._(
                    'Rounding requires a whole-shift rule and a threshold from 1 to 59 minutes, or zero for exact hours.'))
        for ruleset in self.ruleset_id:
            shift_rules = ruleset.rule_ids.filtered(
                lambda rule: rule.base_off == 'quantity' and rule.quantity_period == 'shift')
            if not shift_rules:
                continue
            if shift_rules != ruleset.rule_ids:
                raise ValidationError(self.env._(
                    'Whole-shift rules cannot be combined with daily, weekly or timing rules in the same ruleset.'))
            if any(shift_rules.mapped('expected_hours_from_contract')):
                raise ValidationError(self.env._(
                    'A whole-shift rule requires an explicit duration to exceed.'))
            if len(shift_rules) > 1 and any(shift_rules.mapped('mdl_shift_rounding_threshold_minutes')):
                raise ValidationError(self.env._(
                    'A ruleset with whole-shift rounding must contain exactly one rule.'))

    def _mdl_rounded_shift_hours(self, hours):
        self.ensure_one()
        threshold = self.mdl_shift_rounding_threshold_minutes
        if not threshold:
            return hours
        whole_hours, seconds = divmod(round(max(hours, 0) * 3600), 3600)
        return float(whole_hours + (seconds >= threshold * 60))

    @api.depends('base_off', 'quantity_period', 'expected_hours',
                 'expected_hours_from_contract', 'timing_type', 'resource_calendar_id')
    def _compute_information_display(self):
        shift_rules = self.filtered(
            lambda rule: rule.base_off == 'quantity' and rule.quantity_period == 'shift')
        super(HrAttendanceOvertimeRule, self - shift_rules)._compute_information_display()
        for rule in shift_rules:
            rule.information_display = self.env._(
                '%(hours)s h / whole shift', hours='%g' % rule.expected_hours)

    def _generate_overtime_vals_v2(self, min_check_in, max_check_out, attendances,
                                   schedules_intervals_by_employee):
        shift_rules = self.filtered(
            lambda rule: rule.base_off == 'quantity' and rule.quantity_period == 'shift')
        values = super(HrAttendanceOvertimeRule, self - shift_rules)._generate_overtime_vals_v2(
            min_check_in, max_check_out, attendances, schedules_intervals_by_employee)
        if shift_rules:
            values += shift_rules._mdl_generate_shift_overtime_vals(attendances)
        return values

    def _generate_overtime_vals(self, employee, attendances, version_map):
        # Keep the older native entry point usable for integrations as well.
        shift_rules = self.filtered(
            lambda rule: rule.base_off == 'quantity' and rule.quantity_period == 'shift')
        values = super(HrAttendanceOvertimeRule, self - shift_rules)._generate_overtime_vals(
            employee, attendances, version_map)
        if shift_rules:
            values += shift_rules._mdl_generate_shift_overtime_vals(attendances)
        return values

    def _mdl_generate_shift_overtime_vals(self, attendances):
        """Reuse native interval/rate helpers without the per-calendar-day reset.

        One business workday contains all attendances beginning on the same
        employee-local date. Full effective intervals remain intact across
        midnight. Keeping interval records distinct avoids the native daily
        helper's overwrite/repeated-attendance problem with segmented work.
        """
        values = []
        for employee, employee_attendances in attendances.filtered('check_out').grouped('employee_id').items():
            by_workday = employee_attendances.grouped(
                lambda attendance: attendance._get_localized_times()[0].date())
            for workday, workday_attendances in by_workday.items():
                effective = Intervals([
                    interval
                    for attendance in workday_attendances
                    # UTC elapsed durations stay correct through both DST
                    # transitions; only the workday key uses local time.
                    for interval in attendance._effective_work_intervals()
                ], keep_distinct=True)
                total_hours = sum_intervals(effective)
                by_attendance = defaultdict(list)
                shortages = []
                for rule in self:
                    excess = total_hours - rule.expected_hours
                    company = rule.company_id or employee.company_id
                    if company.absence_management and float_compare(excess, -rule.employee_tolerance, 5) < 0:
                        shortages.append((excess, rule))
                    elif float_compare(excess, rule.employer_tolerance, 5) > 0:
                        for start, stop, attendance in _last_hours_as_intervals(list(effective), excess):
                            attendance.ensure_one()
                            by_attendance[attendance].append((start, stop, rule))

                workday_values = []

                def append_value(attendance, rules, duration):
                    workday_values.append({
                        'time_start': attendance.check_in,
                        'time_stop': attendance.check_out,
                        'duration': round(duration, 4),
                        'employee_id': employee.id,
                        'date': workday,
                        'rule_ids': rules.ids,
                        **rules._extra_overtime_vals(),
                    })

                for attendance, intervals in by_attendance.items():
                    durations = defaultdict(float)
                    for start, stop, rules in _record_overlap_intervals(intervals):
                        durations[rules] += (stop - start).total_seconds() / 3600
                    for rules, duration in durations.items():
                        append_value(attendance, rules, duration)
                if shortages:
                    duration, rules = max(shortages, key=lambda item: item[0])
                    append_value(workday_attendances.sorted('check_out')[-1], rules, duration)
                rounded_rule = self.filtered('mdl_shift_rounding_threshold_minutes')
                positive_values = [value for value in workday_values if value['duration'] > 0]
                if rounded_rule and positive_values:
                    rounded_rule.ensure_one()
                    raw_total = sum(value['duration'] for value in positive_values)
                    payable_total = rounded_rule._mdl_rounded_shift_hours(
                        total_hours - rounded_rule.expected_hours)
                    if not payable_total:
                        workday_values = [value for value in workday_values if value['duration'] <= 0]
                    else:
                        # Round once for the whole workday, never per punch.
                        # Keep raw physical overtime untouched for the timeline.
                        positive_values.sort(key=lambda value: (value['time_start'], value['time_stop']))
                        allocated = 0.0
                        for index, value in enumerate(positive_values):
                            approval = (payable_total - allocated if index == len(positive_values) - 1
                                        else payable_total * value['duration'] / raw_total)
                            value['manual_duration'] = approval
                            value['mdl_auto_approval_hours'] = approval
                            allocated += approval
                values.extend(workday_values)
        return values

    def _get_all_overtime_intervals_for_timing_rule(
        self, min_check_in, max_check_out, attendances, schedules_intervals_by_employee
    ):
        result = super()._get_all_overtime_intervals_for_timing_rule(
            min_check_in, max_check_out, attendances, schedules_intervals_by_employee)
        filtered = defaultdict(lambda: defaultdict(list))
        for employee, values_by_attendance in result.items():
            for attendance, intervals in values_by_attendance.items():
                # Native timing rules return naive employee-local intervals.
                # Compare in the same timezone, including DST, rather than
                # intersecting them with the segments' stored UTC boundaries.
                work_intervals = attendance._effective_work_intervals(localized=True)
                for start, stop, rules in intervals:
                    for work_start, work_stop, _attendance in work_intervals:
                        overlap_start = max(start, work_start)
                        overlap_stop = min(stop, work_stop)
                        if overlap_start < overlap_stop:
                            filtered[employee][attendance].append((overlap_start, overlap_stop, rules))
        return filtered
