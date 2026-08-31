from collections import defaultdict

from odoo import models


class HrAttendanceOvertimeRule(models.Model):
    _inherit = "hr.attendance.overtime.rule"

    def _get_all_overtime_intervals_for_timing_rule(
        self, min_check_in, max_check_out, attendances, schedules_intervals_by_employee
    ):
        result = super()._get_all_overtime_intervals_for_timing_rule(
            min_check_in, max_check_out, attendances, schedules_intervals_by_employee)
        filtered = defaultdict(lambda: defaultdict(list))
        for employee, values_by_attendance in result.items():
            for attendance, intervals in values_by_attendance.items():
                work_intervals = attendance._effective_work_intervals()
                for start, stop, rules in intervals:
                    for work_start, work_stop, _attendance in work_intervals:
                        overlap_start = max(start, work_start)
                        overlap_stop = min(stop, work_stop)
                        if overlap_start < overlap_stop:
                            filtered[employee][attendance].append((overlap_start, overlap_stop, rules))
        return filtered
