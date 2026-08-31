from datetime import datetime, time

import pytz

from odoo import models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def _update_overtime(self, attendance_domain=None):
        result = super()._update_overtime(attendance_domain=attendance_domain)
        if not self.env.context.get('install_demo'):
            affected = self.filtered('check_out')
            if attendance_domain:
                affected |= self.search(attendance_domain).filtered('check_out')
            affected._mdl_remove_additional_day_overtimes()
        return result

    def _mdl_remove_additional_day_overtimes(self):
        """Keep a monthly off-schedule day out of Odoo's overtime bucket.

        Odoo correctly sees zero expected hours and initially classifies all
        attendance as overtime.  In the Israeli monthly layer that same day is
        a single fixed-rate additional day, so the native overtime rows must
        not remain visible or become payable as well.
        """
        additional_type = self.env.ref(
            'l10n_il_hr_payroll.work_entry_type_additional_day')
        additional_keys = set()
        for attendance in self:
            version = attendance.employee_id.sudo()._get_version(attendance.date)
            if (not version
                    or version.mdl_wage_type != 'mdl_monthly'
                    or version.work_entry_source != 'attendance'):
                continue
            tz = pytz.timezone(version._get_tz() or 'UTC')
            day_start = tz.localize(
                datetime.combine(attendance.date, time.min)
            ).astimezone(pytz.utc).replace(tzinfo=None)
            day_stop = tz.localize(
                datetime.combine(attendance.date, time.max)
            ).astimezone(pytz.utc).replace(tzinfo=None)
            values = version._mdl_get_normalized_work_entry_vals(
                day_start, day_stop)
            if any(
                    value.get('work_entry_type_id') == additional_type.id
                    for value in values):
                additional_keys.add((attendance.employee_id.id, attendance.date))

        if not additional_keys:
            return
        overtime_lines = self.env['hr.attendance.overtime.line']
        for employee_id, work_date in additional_keys:
            overtime_lines |= self.env['hr.attendance.overtime.line'].search([
                ('employee_id', '=', employee_id),
                ('date', '=', work_date),
            ])
        overtime_lines.unlink()
        self.env.add_to_compute(self._fields['overtime_hours'], self)
        self.env.add_to_compute(self._fields['validated_overtime_hours'], self)
        self.env.add_to_compute(self._fields['overtime_status'], self)

    def _create_work_entries(self):
        """עבור עובדי השכבה המנורמלת אין ליצור רשומת עבודה פר החתמה — יש
        לחולל מחדש את כל רשומות היום העסקי, כדי שהקיבוץ, העיגול והסיווג
        יבוצעו תמיד על כלל החתמות היום (סעיף 23 באפיון)."""
        # Odoo.sh loads demo attendances after all custom modules are already
        # installed.  They are sample records only and must not trigger the
        # custom payroll work-entry regeneration used for real attendances.
        if self.env.context.get('install_demo'):
            return

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
