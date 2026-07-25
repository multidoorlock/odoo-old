import pytz

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    attendance_type = fields.Selection(
        selection=[("morning", "משמרת בוקר"), ("afternoon", "משמרת ערב")],
        string="סוג משמרת", readonly=True, tracking=True, copy=False,
        help="נקבע אוטומטית לפי שעת הכניסה וחוקי המשמרות של העובד "
             "(רק לעובד שסוג רשומת הנוכחות שלו הוא 'משמרות').",
    )

    def _get_tz_for_employee(self, employee):
        return pytz.timezone(employee._get_tz() or "UTC")

    def _local_hour(self, dt, employee):
        if not dt:
            return None
        local = pytz.utc.localize(dt).astimezone(self._get_tz_for_employee(employee))
        return local.hour + local.minute / 60.0 + local.second / 3600.0

    def _classify_check_in(self, employee, check_in):
        """מחזיר את סוג המשמרת (morning/afternoon) לפי שעת הכניסה - רק לעובד
        שסוג רשומת הנוכחות שלו הוא 'משמרות'; אחרת False (נוכחות רגילה)."""
        version = employee.sudo()._get_version(check_in.date())
        if version.att_record_type != "shifts" or not version.att_classification_ruleset_id:
            return False
        hour = self._local_hour(check_in, employee)
        return version.att_classification_ruleset_id._match_attendance_type(hour)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            check_in = fields.Datetime.to_datetime(vals.get("check_in"))
            employee_id = vals.get("employee_id")
            if check_in and employee_id:
                employee = self.env["hr.employee"].browse(employee_id)
                vals["attendance_type"] = self._classify_check_in(employee, check_in)
        return super().create(vals_list)

    def write(self, vals):
        check_in = fields.Datetime.to_datetime(vals.get("check_in"))
        if not check_in:
            return super().write(vals)
        for attendance in self:
            record_vals = dict(vals, attendance_type=self._classify_check_in(attendance.employee_id, check_in))
            super(HrAttendance, attendance).write(record_vals)
        return True
