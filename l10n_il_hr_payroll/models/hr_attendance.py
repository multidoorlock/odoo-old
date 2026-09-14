from datetime import datetime, time

import pytz

from odoo import models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    def _update_overtime(self, attendance_domain=None):
        affected_domain = attendance_domain or self._get_overtimes_to_update_domain()
        if hasattr(self, '_mdl_whole_shift_attendance_domain'):
            # This may include check_in filters.  Use it only to find nearby
            # attendances, never as the shared Odoo overtime-line domain.
            affected_domain = self._mdl_whole_shift_attendance_domain(
                affected_domain)
        result = super()._update_overtime(attendance_domain=attendance_domain)
        if not self.env.context.get('install_demo'):
            affected = self.filtered('check_out')
            affected |= self.search(affected_domain).filtered('check_out')
            affected._mdl_remove_additional_day_overtimes()
            if hasattr(affected, '_mdl_sync_shift_overtime_marks'):
                # Additional-day classification runs after native overtime.
                # Refresh only its visual tail, retaining the source partition.
                affected._mdl_sync_shift_overtime_marks()
        return result

    def _mdl_remove_additional_day_overtimes(self):
        """Keep an off-schedule day out of Odoo's overtime bucket.

        Odoo correctly sees zero expected hours and initially classifies all
        attendance as overtime.  In the Israeli payroll layer that same day is
        a single additional day, so native overtime rows must not remain
        visible or become payable as well.
        """
        additional_keys = set()
        for attendance in self:
            version = attendance.employee_id.sudo()._get_version(attendance.date)
            if (not version
                    or version.work_entry_source not in ('attendance', 'calendar')):
                continue
            additional_type = version.company_id._mdl_additional_day_type()
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

        def uses_mdl_work_entries(attendance):
            version = attendance.employee_id.sudo()._get_version(
                attendance.date)
            return bool(
                version
                and version.resource_calendar_id
                and (
                    version.work_entry_source == 'attendance'
                    or version.work_entry_source == 'calendar'
                )
            )

        mdl_attendances = self.filtered(uses_mdl_work_entries)
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
                if not (
                        version.work_entry_source == 'attendance'
                        or version.work_entry_source == 'calendar'):
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
