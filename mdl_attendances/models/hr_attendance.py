import pytz

from odoo import models


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    def _get_tz_for_employee(self, employee):
        return pytz.timezone(employee._get_tz() or "UTC")

    def _local_hour(self, dt, employee):
        if not dt:
            return None
        local = pytz.utc.localize(dt).astimezone(self._get_tz_for_employee(employee))
        return local.hour + local.minute / 60.0 + local.second / 3600.0

    def _classify_check_in(self, employee, check_in):
        """מחזיר את סוג המשמרת (morning/afternoon) לפי שעת הכניסה - רק לעובד
        שלוח הזמנים שלו (resource.calendar) מסוג 'משמרות'; אחרת False (נוכחות
        רגילה). "מה נחשב" כל משמרת מוגדר על הלוח עצמו (attendance_ids עם
        day_period=morning/afternoon), לא בטבלת-כללים נפרדת.

        מחזיר במכוון רק morning/afternoon/False (לא כולל את שכבת יום שישי/שבת,
        ראו _is_l10n_il_weekend_check_in למטה) - הכלל של השעות הנוספות
        (hr_attendance_overtime_rule.att_attendance_type) משווה שוויון מדויק
        מול 'morning'/'afternoon' בלבד, ושינוי הערך המוחזר כאן היה שובר את
        הזיהוי של שעות נוספות בכל משמרת שישי/שבת בשקט.

        מחושב תמיד על-הטופס (לא מאוחסן על רשומת הנוכחות עצמה - היא נשארת
        רשומה סטנדרטית של Odoo לחלוטין, בלי שום שדה נוסף) - נקרא הן בהמרה
        ל-work entry (hr_version._get_real_attendance_work_entry_vals) והן
        במנוע השעות הנוספות (hr_attendance_overtime_rule).
        """
        version = employee.sudo()._get_version(check_in.date())
        calendar = version.resource_calendar_id
        if not calendar or calendar.l10n_il_schedule_type != "shifts":
            return False
        hour = self._local_hour(check_in, employee)
        # כלל הסיווג של הלקוח בפועל (ShiftCutoffHour=12 בקובץ מערכת השכר):
        # כניסה לפני 12:00 = בוקר, אחרי = ערב. עדיף על התאמת-בלוקים מדויקת מול
        # הלוח, שנשברת על כניסות מוקדמות (למשל 06:20, לפני תחילת בלוק הבוקר
        # 06:30 - נופלת בטעות לתוך "המשך הערב" של [00:00,06:30) ומסווגת ערב).
        return "morning" if hour < 12.0 else "afternoon"

    def _is_l10n_il_weekend_check_in(self, employee, check_in):
        """True כאשר הכניסה חלה ביום שישי/שבת מקומי (סוף השבוע בישראל) -
        שכבה נפרדת מסיווג הבוקר/ערב (_classify_check_in), נבדקת רק בעת בחירת
        סוג רשומת העבודה הסופי (ראו hr_version._get_real_attendance_work_entry_vals),
        לא במנוע השעות הנוספות."""
        local_date = pytz.utc.localize(check_in).astimezone(self._get_tz_for_employee(employee)).date()
        return local_date.weekday() in (4, 5)  # ישראל: שישי=4, שבת=5 (Python weekday, Monday=0)
