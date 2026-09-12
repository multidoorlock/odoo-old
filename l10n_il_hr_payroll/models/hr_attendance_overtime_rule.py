from collections import defaultdict

from odoo import fields, models


class HrAttendanceOvertimeRule(models.Model):
    _inherit = 'hr.attendance.overtime.rule'

    mdl_morning_shift_only = fields.Boolean(
        string='Morning Shift Only', default=False,
        help="Apply this timing rule only to attendances that start before the "
             "company's morning/evening cutoff. Applies to working-day timing rules only.")

    def _get_all_overtime_intervals_for_timing_rule(
            self, min_check_in, max_check_out, attendances,
            schedules_intervals_by_employee):
        values = super()._get_all_overtime_intervals_for_timing_rule(
            min_check_in, max_check_out, attendances,
            schedules_intervals_by_employee)
        result = defaultdict(lambda: defaultdict(list))
        for employee, by_attendance in values.items():
            for attendance, intervals in by_attendance.items():
                # Match the payroll shift classifier: local check-in strictly
                # before the employee company's configured morning cutoff.
                local_start, _local_stop = attendance._get_localized_times()
                start_hour = local_start.hour + local_start.minute / 60.0
                morning = start_hour < attendance.employee_id.company_id.mdl_shift_cutoff
                for start, stop, rules in intervals:
                    applicable = rules.filtered(lambda rule: (
                        not rule.mdl_morning_shift_only
                        or rule.base_off != 'timing'
                        or rule.timing_type != 'work_days'
                        or morning
                    ))
                    if applicable:
                        result[employee][attendance].append((start, stop, applicable))
        return result
