from datetime import datetime, time

import pytz

from odoo import models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def _create_work_entries(self):
        """עבור עובדי השכבה המנורמלת אין ליצור רשומת עבודה פר החתמה — יש
        לחולל מחדש את כל רשומות היום העסקי, כדי שהקיבוץ, העיגול והסיווג
        יבוצעו תמיד על כלל החתמות היום (סעיף 23 באפיון)."""
        mdl_attendances = self.filtered(
            lambda attendance: attendance.employee_id.sudo().version_id.work_entry_source == 'attendance'
            and attendance.employee_id.sudo().version_id.resource_calendar_id)
        standard_attendances = self - mdl_attendances
        if standard_attendances:
            super(HrAttendance, standard_attendances)._create_work_entries()
        if not mdl_attendances:
            return

        slots = []
        seen = set()
        for attendance in mdl_attendances:
            if not attendance.check_out:
                continue
            versions = attendance.employee_id.sudo()._get_versions_with_contract_overlap_with_period(
                attendance.check_in.date(), attendance.check_out.date())
            for version in versions:
                if version.work_entry_source != 'attendance':
                    continue
                # יצירה ישירה רק בתוך תקופה שכבר חוללה — כמו במנגנון הסטנדרטי,
                # אך ברמת יום עסקי שלם: אם חלק כלשהו מהיום נמצא בטווח שנוצר,
                # יש לחולל מחדש את כל היום.
                tz = pytz.timezone(version._get_tz() or 'UTC')
                day_start = tz.localize(
                    datetime.combine(attendance.date, time.min)
                ).astimezone(pytz.utc).replace(tzinfo=None)
                day_stop = tz.localize(
                    datetime.combine(attendance.date, time.max)
                ).astimezone(pytz.utc).replace(tzinfo=None)
                if (day_stop >= version.date_generated_from
                        and day_start <= version.date_generated_to):
                    key = (attendance.employee_id.id, attendance.date)
                    if key not in seen:
                        seen.add(key)
                        slots.append({
                            'date': attendance.date,
                            'employee_id': attendance.employee_id.id,
                        })
        if slots:
            self.env['hr.work.entry.regeneration.wizard'].sudo().regenerate_work_entries(slots=slots)
