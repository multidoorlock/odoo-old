"""מנוע יצירת רשומות עבודה מנורמלות מנתוני נוכחות (סעיפים 17–34 באפיון).

המנוע מוטמע בנקודת ההרחבה הסטנדרטית _get_work_entries_values של hr.version,
ולכן פועל באופן זהה ביצירה שוטפת של רשומות עבודה, ביצירת תלושים וב־Regenerate.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import Command, fields, models
from odoo.tools import float_compare


class HrVersion(models.Model):
    _inherit = 'hr.version'

    def _get_work_entries_values(self, date_start, date_stop):
        if self.env.context.get('install_demo'):
            return super()._get_work_entries_values(date_start, date_stop)

        vals_list = super()._get_work_entries_values(date_start, date_stop)
        mdl_versions = self.sudo().filtered(
            lambda v: v.work_entry_source == 'attendance' and v.resource_calendar_id)
        if not mdl_versions:
            return vals_list
        # הסרת רשומות הנוכחות הגולמיות שהמנגנון הסטנדרטי יצר עבור עובדי
        # השכבה שלנו (רשומות חופשה ולוח נשארות כפי שהן), והחלפתן ברשומות
        # מנורמלות ברמת יום עבודה.
        mdl_version_ids = set(mdl_versions.ids)
        vals_list = [
            vals for vals in vals_list
            if not ((vals.get('attendance_id') or vals.get('overtime_id'))
                    and vals.get('version_id') in mdl_version_ids)
        ]
        for version in mdl_versions:
            vals_list += version._mdl_get_normalized_work_entry_vals(date_start, date_stop)
            # המנוע מחולל תמיד ימים שלמים — יש להצמיד את גבולות התקופה שנוצרה
            # לגבולות יום שלם, אחרת החתמה נוספת מאוחר יותר באותו יום תיפול
            # מחוץ לטווח, וחילול עתידי שיתחיל באמצע יום יכפיל רשומות.
            window = version._mdl_window_bounds(date_start, date_stop)
            if window:
                generated_from, generated_to = window
                if version.date_generated_from > generated_from:
                    version.date_generated_from = generated_from
                if version.date_generated_to < generated_to:
                    version.date_generated_to = generated_to
        return vals_list

    def _mdl_localized_window(self, date_start, date_stop):
        """המרת חלון החילול (datetime נאיבי ב־UTC או תאריכים) לטווח ימים
        עסקיים באזור הזמן של העובד. מחזיר (tz, יום ראשון, יום אחרון)."""
        self.ensure_one()
        tz = pytz.timezone(self.sudo()._get_tz() or 'UTC')
        if not isinstance(date_start, datetime):
            date_start = tz.localize(
                datetime.combine(fields.Date.to_date(date_start), time.min)
            ).astimezone(pytz.utc).replace(tzinfo=None)
            date_stop = tz.localize(
                datetime.combine(fields.Date.to_date(date_stop), time.max)
            ).astimezone(pytz.utc).replace(tzinfo=None)
        # Payroll generation normally passes naive UTC datetimes, while the
        # Work Entries Gantt progress-bar path passes timezone-aware values.
        # Accept both forms instead of localizing an already-aware datetime.
        start_utc = (
            pytz.utc.localize(date_start)
            if date_start.tzinfo is None
            else date_start.astimezone(pytz.utc)
        )
        stop_utc = (
            pytz.utc.localize(date_stop)
            if date_stop.tzinfo is None
            else date_stop.astimezone(pytz.utc)
        )
        start_local = start_utc.astimezone(tz)
        stop_local = stop_utc.astimezone(tz)
        first_day = start_local.date()
        # Odoo uses the previous generated boundary (local time.max) as the
        # beginning of the next incremental generation interval. Expanding
        # that single boundary microsecond back to the whole same day creates
        # a duplicate normalized work entry when a payslip is opened.
        if start_local.time() == time.max:
            first_day += timedelta(days=1)
        last_day = (stop_local - timedelta(microseconds=1)).date()
        return tz, first_day, last_day

    def _mdl_window_bounds(self, date_start, date_stop):
        """גבולות החלון ב־UTC נאיבי, מוצמדים לימים עסקיים שלמים."""
        tz, first_day, last_day = self._mdl_localized_window(date_start, date_stop)
        if last_day < first_day:
            return None
        generated_from = tz.localize(
            datetime.combine(first_day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        generated_to = tz.localize(
            datetime.combine(last_day, time.max)).astimezone(pytz.utc).replace(tzinfo=None)
        return generated_from, generated_to

    # ------------------------------------------------------------------
    # המנוע
    # ------------------------------------------------------------------

    def _mdl_get_normalized_work_entry_vals(self, date_start, date_stop):
        self.ensure_one()
        version = self.sudo()
        employee = version.employee_id
        calendar = version.resource_calendar_id
        company = version.company_id or self.env.company
        tz, first_day, last_day = self._mdl_localized_window(date_start, date_stop)
        if last_day < first_day:
            return []

        schedule_type = calendar.mdl_schedule_type
        frequency = calendar.mdl_schedule_frequency
        weekly = frequency == 'weekly_quota'
        monthly_worker = version.mdl_wage_type != 'mdl_daily'
        std_day_hours = calendar.hours_per_day or 0.0
        today_local = pytz.utc.localize(datetime.utcnow()).astimezone(tz).date()

        def week_anchor(day):
            # שבוע העבודה מתחיל ביום ראשון.
            return day - timedelta(days=(day.weekday() + 1) % 7)

        # במכסה שבועית יש לחשב את הניצול מתחילת השבוע גם אם החלון מתחיל באמצעו.
        fetch_first_day = week_anchor(first_day) if weekly else first_day

        fetch_start_utc = tz.localize(
            datetime.combine(fetch_first_day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        fetch_stop_utc = tz.localize(
            datetime.combine(last_day, time.max)).astimezone(pytz.utc).replace(tzinfo=None)
        attendances = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_out', '!=', False),
            ('check_in', '>=', fetch_start_utc),
            ('check_in', '<=', fetch_stop_utc),
        ], order='check_in asc')
        attendances_by_day = defaultdict(lambda: self.env['hr.attendance'].sudo())
        for attendance in attendances:
            local_day = pytz.utc.localize(attendance.check_in).astimezone(tz).date()
            attendances_by_day[local_day] += attendance

        # Odoo's overtime rules remain the sole source of paid overtime when a
        # ruleset is assigned. The normalization layer only replaces regular
        # attendance rows; it must preserve the rule-selected work-entry type
        # and duration instead of inventing a second weekend/overtime path.
        overtime_by_day = defaultdict(
            lambda: self.env['hr.attendance.overtime.line'].sudo())
        if version.ruleset_id:
            overtime_lines = self.env['hr.attendance.overtime.line'].sudo().search([
                ('employee_id', '=', employee.id),
                ('date', '>=', fetch_first_day),
                ('date', '<=', last_day),
                ('status', '=', 'approved'),
                ('manual_duration', '>', 0),
                ('work_entry_type_overtime_id', '!=', False),
            ])
            for overtime in overtime_lines:
                overtime_by_day[overtime.date] += overtime

        # שעות מתוכננות ושעות חופשה מאושרת לכל יום (ללוחות קבועים/מכסה יומית).
        scheduled_by_day = defaultdict(float)
        leave_by_day = defaultdict(float)
        if frequency in ('fixed_intervals', 'daily_duration'):
            resource = employee.resource_id
            span_start = tz.localize(datetime.combine(fetch_first_day, time.min))
            span_stop = tz.localize(datetime.combine(last_day, time.max))
            work_intervals = calendar._attendance_intervals_batch(
                span_start, span_stop, resources=resource)[resource.id]
            leave_intervals = calendar._leave_intervals_batch(
                span_start, span_stop, resources=resource)[resource.id]
            for interval_start, interval_stop, _records in work_intervals:
                scheduled_by_day[interval_start.date()] += (
                    (interval_stop - interval_start).total_seconds() / 3600)
            for interval_start, interval_stop, _records in (work_intervals & leave_intervals):
                leave_by_day[interval_start.date()] += (
                    (interval_stop - interval_start).total_seconds() / 3600)

        type_regular = self.env.ref('hr_work_entry.work_entry_type_attendance')
        type_overtime = self.env.ref('hr_work_entry.work_entry_type_overtime')
        type_additional = self.env.ref('l10n_il_hr_payroll.work_entry_type_additional_day')
        type_sleep = self.env.ref('l10n_il_hr_payroll.work_entry_type_sleep')
        type_absence = self.env.ref('l10n_il_hr_payroll.work_entry_type_unpaid_absence')
        category_types = {
            'regular': type_regular,
            'additional_day': type_additional,
        }

        def make_vals(day, entry_type, duration, category, shift_type, reason,
                      day_attendances, actual_hours):
            vals = {
                'name': '%s: %s' % (entry_type.sudo().name, employee.name),
                'date': day,
                'duration': duration,
                'work_entry_type_id': entry_type.id,
                'employee_id': employee.id,
                'version_id': version.id,
                'company_id': company.id,
                'mdl_actual_hours': actual_hours,
                'mdl_normalized_hours': duration,
                'mdl_rate_category': category,
                'mdl_shift_type': shift_type,
                'mdl_rounding_reason': reason,
            }
            if day_attendances:
                vals['attendance_id'] = day_attendances[0].id
                vals['mdl_source_attendance_ids'] = [Command.set(day_attendances.ids)]
            return vals

        def rounded_overtime(raw_hours):
            """עיגול שעות נוספות לפי סף 40 דקות (סעיף 26 באפיון)."""
            raw_seconds = int(round(max(raw_hours, 0.0) * 3600))
            whole_hours, remaining_seconds = divmod(raw_seconds, 3600)
            return whole_hours + (1 if remaining_seconds >= 2400 else 0)

        quota_hours = calendar.hours_per_week if weekly else 0.0
        quota_shifts = calendar.mdl_shifts_per_week if weekly else 0
        consumed_hours = 0.0
        consumed_shifts = 0
        current_week = week_anchor(fetch_first_day)

        result = []
        day = fetch_first_day
        while day <= last_day:
            if weekly and week_anchor(day) != current_week:
                current_week = week_anchor(day)
                consumed_hours = 0.0
                consumed_shifts = 0

            emit = day >= first_day
            day_attendances = attendances_by_day.get(day)
            day_overtimes = overtime_by_day[day]
            native_overtime_hours = sum(day_overtimes.mapped('manual_duration'))
            day_vals = []

            if schedule_type == 'shifts':
                consumed_shifts = self._mdl_process_shift_day(
                    day_vals, make_vals, day, day_attendances,
                    frequency, monthly_worker, company, tz,
                    scheduled_by_day, leave_by_day, today_local,
                    quota_shifts, consumed_shifts, category_types, type_sleep,
                    type_overtime, type_absence, rounded_overtime,
                    native_overtime_hours, bool(version.ruleset_id))
            else:
                consumed_hours = self._mdl_process_regular_day(
                    day_vals, make_vals, day, day_attendances,
                    frequency, monthly_worker, std_day_hours,
                    scheduled_by_day, leave_by_day, today_local,
                    quota_hours, consumed_hours, category_types,
                    type_overtime, type_absence, rounded_overtime,
                    native_overtime_hours, bool(version.ruleset_id))

            total_actual_hours = sum(
                attendance.worked_hours for attendance in (day_attendances or []))
            # A monthly employee's day outside the schedule (or beyond a
            # weekly quota) is one additional day. Odoo may still create
            # overtime lines because its native expected duration is zero.
            # They must not replace the additional day or be paid on top of it.
            is_additional_day = any(
                vals.get('work_entry_type_id') == type_additional.id
                for vals in day_vals
            )
            if not is_additional_day:
                for overtime in day_overtimes:
                    overtime_vals = make_vals(
                        day, overtime.work_entry_type_overtime_id,
                        overtime.manual_duration, 'regular', 'none',
                        'odoo_overtime_rule', day_attendances, total_actual_hours)
                    overtime_vals['overtime_id'] = overtime.id
                    day_vals.append(overtime_vals)

            if emit:
                result += day_vals
            day += timedelta(days=1)
        return result

    def _mdl_process_regular_day(self, day_vals, make_vals, day, day_attendances,
                                 frequency, monthly_worker, std_day_hours,
                                 scheduled_by_day, leave_by_day, today_local,
                                 quota_hours, consumed_hours, category_types,
                                 type_overtime, type_absence, rounded_overtime,
                                 native_overtime_hours, uses_overtime_rules):
        # Segmentation is the canonical source of effective work.  Presence
        # may include sleep/break windows and must never feed quota/overtime.
        total_actual_hours = sum(
            attendance.worked_hours for attendance in (day_attendances or []))
        scheduled_hours = scheduled_by_day.get(day, 0.0)

        if frequency in ('fixed_intervals', 'daily_duration'):
            if scheduled_hours:
                category = 'regular'
                h_date = scheduled_hours
            else:
                category = 'additional_day' if monthly_worker else 'regular'
                h_date = std_day_hours

        else:  # מכסה שבועית
            remaining = quota_hours - consumed_hours
            if float_compare(remaining, 0.0, precision_digits=2) > 0:
                category = 'regular'
                h_date = min(std_day_hours, remaining)
            else:
                category = 'additional_day' if monthly_worker else 'regular'
                h_date = std_day_hours

        # All effective attendance on an additional day belongs to that day.
        # Native overtime created from zero expected hours is ignored here.
        applied_native_overtime = (
            0.0 if category == 'additional_day' else native_overtime_hours
        )
        actual_hours = max(total_actual_hours - applied_native_overtime, 0.0)

        # עיגול לחצי יום / יום מלא (סעיף 24 באפיון).
        normalized_hours = 0.0
        reason = 'full_day'
        if actual_hours > 0 and h_date > 0:
            half_day = h_date / 2
            if float_compare(actual_hours, half_day, precision_digits=6) <= 0:
                normalized_hours, reason = half_day, 'half_day'
            else:
                normalized_hours, reason = h_date, 'full_day'
        if normalized_hours:
            day_vals.append(make_vals(
                day, category_types[category], normalized_hours, category,
                'none', reason, day_attendances, actual_hours))

        # הפרדת שעות נוספות מעבר למכסה היומית (סעיפים 25–26 באפיון).
        overtime_hours = (
            0.0 if (uses_overtime_rules or category == 'additional_day')
            else rounded_overtime(actual_hours - h_date)
        )
        if overtime_hours:
            day_vals.append(make_vals(
                day, type_overtime, overtime_hours, category,
                'none', 'overtime_threshold', day_attendances, actual_hours))

        weekly = frequency == 'weekly_quota'
        if weekly and category == 'regular':
            consumed_hours += normalized_hours

        # היעדרות ללא תשלום עבור זמן מתוכנן שלא בוצע — רק בלוחות קבועים/מכסה
        # יומית, רק לימים שכבר חלפו, ובקיזוז חופשה מאושרת.
        if (not monthly_worker
                and frequency in ('fixed_intervals', 'daily_duration')
                and scheduled_hours and day < today_local):
            absence_hours = max(
                scheduled_hours - normalized_hours - leave_by_day.get(day, 0.0), 0.0)
            if float_compare(absence_hours, 0.0, precision_digits=2) > 0:
                day_vals.append(make_vals(
                    day, type_absence, absence_hours, category, 'none',
                    'half_day' if normalized_hours else 'full_day',
                    day_attendances, actual_hours))
        return consumed_hours

    def _mdl_process_shift_day(self, day_vals, make_vals, day, day_attendances,
                               frequency, monthly_worker, company, tz,
                               scheduled_by_day, leave_by_day, today_local,
                               quota_shifts, consumed_shifts, category_types,
                               type_sleep, type_overtime, type_absence,
                               rounded_overtime, native_overtime_hours,
                               uses_overtime_rules):
        cutoff = company.mdl_shift_cutoff
        scheduled_hours = scheduled_by_day.get(day, 0.0)

        buckets = []
        if day_attendances:
            def local_hour(attendance):
                check_in_local = pytz.utc.localize(attendance.check_in).astimezone(tz)
                return check_in_local.hour + check_in_local.minute / 60.0

            morning = day_attendances.filtered(lambda a: local_hour(a) < cutoff)
            evening = day_attendances - morning
            if morning:
                buckets.append(('morning', morning))
            if evening:
                buckets.append(('evening', evening))

        for shift_type, shift_attendances in buckets:
            paid_hours = (
                company.mdl_shift_morning_hours
                if shift_type == 'morning'
                else company.mdl_shift_evening_hours
            )
            total_actual_hours = sum(
                attendance.worked_hours for attendance in shift_attendances)

            def presence_hours(attendance):
                # mdl_attendances adds the explicit presence_hours field, but
                # the payroll module is also valid without that optional UI
                # layer.  In that case presence is the raw check-in/out span.
                if 'presence_hours' in attendance._fields:
                    return attendance.presence_hours
                if not attendance.check_in or not attendance.check_out:
                    return attendance.worked_hours
                return (
                    attendance.check_out - attendance.check_in
                ).total_seconds() / 3600.0

            non_work_hours = sum(
                max(presence_hours(attendance) - attendance.worked_hours, 0.0)
                for attendance in shift_attendances
            )
            if frequency == 'daily_duration':
                category = ('regular' if scheduled_hours
                            else ('additional_day' if monthly_worker else 'regular'))
            else:  # מכסה שבועית של משמרות
                if consumed_shifts < quota_shifts:
                    category = 'regular'
                else:
                    category = 'additional_day' if monthly_worker else 'regular'
            applied_native_overtime = (
                0.0 if category == 'additional_day' else native_overtime_hours
            )
            actual_hours = max(
                total_actual_hours - applied_native_overtime, 0.0)
            if frequency == 'weekly_quota' and category == 'regular':
                consumed_shifts += 1

            # כל כניסה למשמרת מתעגלת למשמרת מלאה בתשלום.
            if actual_hours:
                day_vals.append(make_vals(
                    day, category_types[category], paid_hours, category,
                    shift_type, 'shift', shift_attendances, total_actual_hours))
            overtime_hours = (
                0.0 if (uses_overtime_rules or category == 'additional_day')
                else rounded_overtime(actual_hours - paid_hours)
            )
            if overtime_hours:
                day_vals.append(make_vals(
                    day, type_overtime, overtime_hours, category,
                    shift_type, 'overtime_threshold', shift_attendances,
                    total_actual_hours))
            if shift_type == 'evening' and non_work_hours > 0:
                day_vals.append(make_vals(
                    day, type_sleep, non_work_hours, category,
                    'evening', 'sleep', shift_attendances, total_actual_hours))

        # משמרת מתוכננת שלא בוצעה — היעדרות ללא תשלום (במכסה יומית בלבד).
        if (not monthly_worker and frequency == 'daily_duration' and scheduled_hours
                and not day_attendances and day < today_local):
            absence_hours = max(scheduled_hours - leave_by_day.get(day, 0.0), 0.0)
            if float_compare(absence_hours, 0.0, precision_digits=2) > 0:
                day_vals.append(make_vals(
                    day, type_absence, absence_hours, 'regular', 'none',
                    'full_day', None, 0.0))
        return consumed_shifts
