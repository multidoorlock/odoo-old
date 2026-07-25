from odoo import fields, models


class HrAttendanceOvertimeRule(models.Model):
    _inherit = "hr.attendance.overtime.rule"

    att_attendance_type = fields.Selection(
        selection=[("any", "כל סוג"), ("morning", "משמרת בוקר"), ("afternoon", "משמרת ערב")],
        string="חל על סוג משמרת", default="any", required=True,
        help="מגביל את הכלל לרישומי נוכחות מסוג משמרת מסוים בלבד, כפי שסווגו על ידי "
             "קבוצת כללי הסיווג של העובד. 'כל סוג' משמעו שהכלל חל ללא תלות בסוג המשמרת.",
    )

    def _generate_overtime_vals_v2(self, min_check_in, max_check_out, attendances, schedules_intervals_by_employee):
        """מריץ את מנוע השעות הנוספות בנפרד לכל קבוצת סוג-משמרת, כך שכלל המוגבל
        לסוג משמרת מסוים יחול רק על רישומי הנוכחות מאותו סוג."""
        vals = []
        for att_type, rules in self.grouped(lambda r: r.att_attendance_type or "any").items():
            filtered_attendances = attendances
            if att_type != "any":
                filtered_attendances = attendances.filtered(lambda a: a.attendance_type == att_type)
            if not filtered_attendances:
                continue
            vals += super(HrAttendanceOvertimeRule, rules)._generate_overtime_vals_v2(
                min_check_in, max_check_out, filtered_attendances, schedules_intervals_by_employee)
        return vals
