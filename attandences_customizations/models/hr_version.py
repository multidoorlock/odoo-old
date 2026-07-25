from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrVersion(models.Model):
    _inherit = "hr.version"

    att_record_type = fields.Selection(
        selection=[("regular", "נוכחות רגילה"), ("shifts", "משמרות")],
        string="סוג רשומת נוכחות", required=True, default="regular",
        groups="hr.group_hr_user", tracking=True,
        help="נוכחות רגילה: נכנסת לשכר כרגיל, ללא סיווג. משמרות: הנוכחות מסווגת "
             "אוטומטית למשמרת בוקר/ערב, ונכנסת לשכר תחת סוגי כניסת העבודה הייעודיים.",
    )
    att_classification_ruleset_id = fields.Many2one(
        "hr.attendance.classification.ruleset",
        string="חוקי משמרות",
        groups="hr.group_hr_manager",
        tracking=True,
        default=lambda self: self.env.ref(
            "attandences_customizations.classification_ruleset_default", raise_if_not_found=False),
        help="חובה כאשר סוג רשומת הנוכחות הוא 'משמרות' - קובע איך מסווגים כניסה למשמרת בוקר/ערב.",
    )
    att_overtime_hourly_rate = fields.Float(
        string="שכר לשעה נוספת",
        digits=(16, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="סכום קבוע בשקלים לכל שעת עבודה נוספת שמקורה בנוכחות (משמרת בוקר לאחר שעת הסף). "
             "התשלום בפועל מחושב לפי שעות (חלקי) ולא לפי אחוז מהשכר הרגיל.",
    )

    @api.constrains("att_record_type", "att_classification_ruleset_id")
    def _check_att_classification_ruleset_required(self):
        for version in self:
            if version.att_record_type == "shifts" and not version.att_classification_ruleset_id:
                raise ValidationError(
                    "יש לבחור חוקי משמרות כאשר סוג רשומת הנוכחות הוא 'משמרות'.")

    def _get_real_attendance_work_entry_vals(self, intervals):
        """מחליף את סוג כניסת העבודה הכללי 'נוכחות' בסוג הספציפי (בוקר/ערב)
        לפי סוג המשמרת שסווג על רישום הנוכחות המקורי."""
        vals = super()._get_real_attendance_work_entry_vals(intervals)
        generic_type = self.env.ref("hr_work_entry.work_entry_type_attendance", raise_if_not_found=False)
        if not generic_type:
            return vals
        type_by_attendance_type = {
            "morning": self.env.ref("attandences_customizations.work_entry_type_morning_attendance").id,
            "afternoon": self.env.ref("attandences_customizations.work_entry_type_afternoon_attendance").id,
        }
        attendance_ids = {
            v["attendance_id"] for v in vals
            if v.get("work_entry_type_id") == generic_type.id and v.get("attendance_id")
        }
        attendance_type_by_id = {
            att.id: att.attendance_type
            for att in self.env["hr.attendance"].sudo().browse(attendance_ids)
        }
        for v in vals:
            if v.get("work_entry_type_id") != generic_type.id or not v.get("attendance_id"):
                continue
            att_type = attendance_type_by_id.get(v["attendance_id"])
            if att_type in type_by_attendance_type:
                v["work_entry_type_id"] = type_by_attendance_type[att_type]
        return vals
