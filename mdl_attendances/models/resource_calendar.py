from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .hr_version import L10N_IL_SHIFT_STANDARD_HOURS

# בלוק שעות "נומינלי" קבוע למשמרת בוקר/ערב, המשמש רק לבניית attendance_ids
# הנגזרות אוטומטית (ראו ResourceCalendar._l10n_il_sync_shift_weekdays) -
# לצורך תאימות עם מנגנוני הליבה של Odoo (חופשות, שעות/שבוע וכו') בלבד.
# הסיווג האמיתי של נוכחות בפועל (hr_attendance.py._classify_check_in) לא
# תלוי בערכים האלה כלל - הוא לפי שעת הכניסה מול ShiftCutoffHour קבוע.
_MORNING_HOUR_FROM, _MORNING_HOUR_TO = 6.5, 16.0
_EVENING_HOUR_FROM = 16.0


class ResourceCalendar(models.Model):
    """"סוג לוח זמנים לעבודה" (l10n_il_schedule_type) - נוכחות או משמרות -
    ובתוך כל אחד, "סוג ספירת שעות" (l10n_il_counting_type) - שעתי/יומי/שבועי
    (שעתי לא קיים במשמרות - אין טעם ב"שעות התחלה/סיום קבועות" למשמרת שבין
    כה נספרת כ-9.5 שעות קבועות לא משנה מתי בפועל).

    נוכחות+שעתי: הקיים המקורי - שעת התחלה/סיום קבועה לכל יום (attendance_ids
    רגיל, hour_from/hour_to, work_entry_type_id).

    נוכחות+יומי: שדה l10n_il_daily_base_hours (מעל הטבלה, לא לכל יום) מגדיר
    "כמה שעות זו יומית אחת". לכל יום ב-attendance_ids יש בחירה
    (ResourceCalendarAttendance.l10n_il_day_kind): "שעות" - מספר שעות ישיר
    לאותו יום; "יומיות" - כפולה (1/1.5/2/2.5/3) של l10n_il_daily_base_hours.
    סה"כ השעות ליום (l10n_il_day_total_hours) לא יכול לעלות על 24.

    נוכחות+שבועי: אין ימים ספציפיים - רק l10n_il_weekly_days (כמה ימים
    בשבוע) ו-l10n_il_weekly_total_hours (סה"כ שעות לכל השבוע), עם סוג רשומת
    נוכחות אחד (l10n_il_weekly_work_entry_type_id).

    משמרות+יומי: לכל אחד מ-7 ימי השבוע (l10n_il_shift_weekday_ids, תמיד 7
    שורות) יש בחירה מ-4: לא עובד/משמרת בוקר/משמרת ערב/משמרת (=גם וגם,
    מסתדר לבד לפי שעת הכניסה בפועל - ראו hr_version.py). attendance_ids
    נגזרות אוטומטית מזה (_l10n_il_sync_shift_weekdays) - לא נערכות ידנית.

    משמרות+שבועי: אין ימים ספציפיים - רק l10n_il_weekly_morning_shifts/
    l10n_il_weekly_afternoon_shifts/l10n_il_weekly_any_shifts (כמה משמרות
    מכל סוג בשבוע).

    משמרות (יומי ושבועי כאחד): סוג רשומת הנוכחות מוגדר ברמת הלוח -
    l10n_il_shift_morning_type_id/l10n_il_shift_afternoon_type_id - לא לכל
    יום בנפרד."""
    _inherit = "resource.calendar"

    l10n_il_schedule_type = fields.Selection(
        [("attendance", "נוכחות"), ("shifts", "משמרות")],
        string="סוג לוח זמנים לעבודה", default="attendance", required=True,
        help="נוכחות: שעתי/יומי/שבועי רגילים. משמרות: בוקר/ערב, מסווג "
             "אוטומטית לפי שעת הכניסה בפועל - רק יומי/שבועי (אין שעתי).",
    )
    l10n_il_counting_type = fields.Selection(
        [("hourly", "שעתי"), ("daily", "יומי"), ("weekly", "שבועי")],
        string="סוג ספירת שעות", default="hourly", required=True,
        help="שעתי: שעת התחלה/סיום קבועה לכל יום (לא זמין בלוח משמרות). "
             "יומי: כמות קבועה לכל יום עבודה. שבועי: אין ימים ספציפיים "
             "קבועים מראש - רק יעד שבועי כולל.",
    )

    # --- נוכחות + יומי ---
    l10n_il_daily_base_hours = fields.Float(
        string="שעות ל'יומית' אחת",
        help="הבסיס שממנו נגזרות בחירות ה'יומיות' (1/1.5/2 וכו') בכל יום "
             "בטבלה למטה - שדה כללי ללוח, לא לכל יום בנפרד.",
    )

    # --- נוכחות + שבועי ---
    l10n_il_weekly_days = fields.Integer(
        string="ימי עבודה בשבוע",
        help="רלוונטי רק בסוג ספירה שבועי: כמה ימים בשבוע העובד עובד - בלי "
             "לקבוע אילו ימים ספציפיים.",
    )
    l10n_il_weekly_total_hours = fields.Float(
        string="סה\"כ שעות עבודה בשבוע",
        help="רלוונטי רק בסוג ספירה שבועי (נוכחות): סך כל שעות העבודה "
             "לשבוע כולו (לא לכל יום בנפרד).",
    )
    l10n_il_weekly_work_entry_type_id = fields.Many2one(
        "hr.work.entry.type", string="סוג רשומת נוכחות",
        help="רלוונטי רק בסוג ספירה שבועי (נוכחות): סוג רשומת העבודה שבו "
             "יסומנו ימי העבודה בשבוע.",
    )

    # --- משמרות (יומי + שבועי) ---
    l10n_il_shift_morning_type_id = fields.Many2one(
        "hr.work.entry.type", string="סוג רשומת נוכחות - משמרת בוקר",
        default=lambda self: self.env.ref("mdl_attendances.work_entry_type_morning_attendance", raise_if_not_found=False),
    )
    l10n_il_shift_afternoon_type_id = fields.Many2one(
        "hr.work.entry.type", string="סוג רשומת נוכחות - משמרת ערב",
        default=lambda self: self.env.ref("mdl_attendances.work_entry_type_afternoon_attendance", raise_if_not_found=False),
    )

    # --- משמרות + יומי ---
    l10n_il_shift_weekday_ids = fields.One2many(
        "mdl.attendance.shift.weekday", "calendar_id", string="ימי משמרת",
        help="7 ימי השבוע - לכל אחד בחירה: לא עובד / משמרת בוקר / משמרת "
             "ערב / משמרת (בוקר או ערב, מסתדר לבד לפי שעת הכניסה בפועל). "
             "רשומות העבודה בפועל (attendance_ids) נגזרות מזה אוטומטית.",
    )

    # --- משמרות + שבועי ---
    l10n_il_weekly_morning_shifts = fields.Integer(string="משמרות בוקר בשבוע")
    l10n_il_weekly_afternoon_shifts = fields.Integer(string="משמרות ערב בשבוע")
    l10n_il_weekly_any_shifts = fields.Integer(
        string="משמרות (בוקר או ערב) בשבוע",
        help="משמרות שיכולות להיות בוקר או ערב - לא משנה איזו.",
    )

    @api.onchange("l10n_il_schedule_type")
    def _onchange_l10n_il_schedule_type(self):
        if self.l10n_il_schedule_type == "shifts" and self.l10n_il_counting_type == "hourly":
            self.l10n_il_counting_type = "daily"

    @api.constrains("l10n_il_schedule_type", "l10n_il_counting_type")
    def _check_l10n_il_counting_type(self):
        for calendar in self:
            if calendar.l10n_il_schedule_type == "shifts" and calendar.l10n_il_counting_type == "hourly":
                raise ValidationError("בלוח משמרות אין סוג ספירת שעות 'שעתי' - יש לבחור 'יומי' או 'שבועי'.")

    def _get_hours_per_day(self):
        """הילידי מחשב ממוצע-שעות-ליום כ-hours_per_week חלקי מספר-ימים - על
        לוח משמרות, attendance_ids מכיל גם את בלוק הבוקר (9.5) וגם את בלוק
        הערב (14.5, כולל שינה) על אותו יום, כך שהילידי סוכם את שניהם ומקבל
        24 שעות "ליום" - שגוי, כי בפועל יום עבודה הוא משמרת *אחת*, לא
        שתיהן. לכן: על לוח משמרות, יום עבודה תמיד 9.5 שעות משולמות - קבוע."""
        self.ensure_one()
        if self.l10n_il_schedule_type == "shifts":
            return L10N_IL_SHIFT_STANDARD_HOURS if self.attendance_ids else 0.0
        return super()._get_hours_per_day()

    def write(self, vals):
        # flexible_hours הילידי (schedule_type='flexible' - "שעות גמישות",
        # מוסתר מהתצוגה שלנו) מבטל בשקט את _compute_hours_per_day הילידי
        # (מדלג על כל לוח עם flexible_hours=True בסינון שלו) - כך ש-
        # hours_per_day נשאר תקוע על ערך ישן ולא מתעדכן לעולם, גם עם
        # ה-override שלנו ל-_get_hours_per_day. אף אחד משלושת סוגי הספירה
        # שלנו (שעתי/יומי/שבועי) לא תואם למושג "שעות גמישות" הילידי - נאכף
        # כאן שיהיה תמיד False בכל כתיבה שנוגעת בסוג הלוח/ספירה שלנו.
        if "l10n_il_schedule_type" in vals or "l10n_il_counting_type" in vals:
            vals = {**vals, "flexible_hours": False}
        res = super().write(vals)
        trigger_fields = {
            "l10n_il_schedule_type", "l10n_il_counting_type",
            "l10n_il_shift_morning_type_id", "l10n_il_shift_afternoon_type_id",
        }
        if trigger_fields & set(vals):
            self._l10n_il_ensure_shift_weekdays()
            self._l10n_il_sync_shift_weekdays()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        # attendance_ids הילידי הוא compute+store+readonly=False שממלא
        # ברירת מחדל (5 ימי עבודה סטנדרטיים, סוג רשומה גנרי) בכל create()
        # שבו הוא לא סופק במפורש - שגוי גם ללוח משמרות (הסוג הגנרי אסור שם,
        # ראו _check_l10n_il_work_entry_type_matches_schedule_type) וגם
        # ליומי/שבועי בכלל (שורות ברירת המחדל לא משתלבות עם l10n_il_day_kind/
        # l10n_il_shift_weekday_ids). מספקים [(5,0,0)] (נקה הכל) במפורש כדי
        # לעקוף את החישוב האוטומטי - _l10n_il_sync_shift_weekdays למטה יבנה
        # את השורות הנכונות בעצמו אם צריך. flexible_hours=False מאותה סיבה
        # כמו ב-write למעלה.
        for vals in vals_list:
            if vals.get("l10n_il_counting_type", "hourly") != "hourly" and "attendance_ids" not in vals:
                vals["attendance_ids"] = [(5, 0, 0)]
            vals.setdefault("flexible_hours", False)
        records = super().create(vals_list)
        records._l10n_il_ensure_shift_weekdays()
        records._l10n_il_sync_shift_weekdays()
        return records

    def _l10n_il_ensure_shift_weekdays(self):
        """מוודא שלכל לוח משמרות+יומי יש בדיוק 7 שורות ימים (0-6, ברירת
        מחדל 'לא עובד') - נוצרות פעם אחת, לעולם לא נמחקות/מתווספות ידנית
        (המשתמש רק משנה את הבחירה בכל שורה קיימת)."""
        for calendar in self:
            if calendar.l10n_il_schedule_type == "shifts" and calendar.l10n_il_counting_type == "daily":
                existing_days = set(calendar.l10n_il_shift_weekday_ids.mapped("dayofweek"))
                missing = [str(d) for d in range(7) if str(d) not in existing_days]
                if missing:
                    self.env["mdl.attendance.shift.weekday"].create([
                        {"calendar_id": calendar.id, "dayofweek": d, "l10n_il_shift_choice": "off"}
                        for d in missing
                    ])

    def _l10n_il_sync_shift_weekdays(self):
        """גוזר את attendance_ids (רק שורות day_period morning/afternoon)
        מ-l10n_il_shift_weekday_ids - "מקור האמת" היחיד לעריכה ב-UI עבור
        לוח משמרות+יומי; attendance_ids הוא ייצוג-פנימי בלבד (דרוש למנוע
        הילידי - חופשות, שעות/שבוע וכו') ולא נערך ידנית. משמרת 'any' יוצרת
        שתי שורות (בוקר+ערב) לאותו יום - אין ניסיון לייצג 'גם וגם' כערך
        יחיד ב-day_period הילידי (morning/lunch/afternoon בלבד)."""
        for calendar in self:
            if not (calendar.l10n_il_schedule_type == "shifts" and calendar.l10n_il_counting_type == "daily"):
                continue
            old = calendar.attendance_ids.filtered(lambda l: l.day_period in ("morning", "afternoon"))
            morning_type = calendar.l10n_il_shift_morning_type_id
            afternoon_type = calendar.l10n_il_shift_afternoon_type_id
            new_lines = []
            for weekday in calendar.l10n_il_shift_weekday_ids:
                day = int(weekday.dayofweek)
                choice = weekday.l10n_il_shift_choice
                if choice in ("morning", "any") and morning_type:
                    new_lines.append((0, 0, {
                        "name": "משמרת בוקר", "dayofweek": str(day),
                        "hour_from": _MORNING_HOUR_FROM, "hour_to": _MORNING_HOUR_TO,
                        "day_period": "morning", "work_entry_type_id": morning_type.id,
                    }))
                if choice in ("afternoon", "any") and afternoon_type:
                    new_lines.append((0, 0, {
                        "name": "משמרת ערב", "dayofweek": str(day),
                        "hour_from": _EVENING_HOUR_FROM, "hour_to": 24.0,
                        "day_period": "afternoon", "work_entry_type_id": afternoon_type.id,
                    }))
                    new_lines.append((0, 0, {
                        "name": "משמרת ערב (המשך)", "dayofweek": str((day + 1) % 7),
                        "hour_from": 0.0, "hour_to": _MORNING_HOUR_FROM,
                        "day_period": "afternoon", "work_entry_type_id": afternoon_type.id,
                    }))
            old.unlink()
            if new_lines:
                calendar.write({"attendance_ids": new_lines})


class MdlAttendanceShiftWeekday(models.Model):
    """יום בשבוע בלוח משמרות (ספירה יומית) - תמיד 7 שורות ללוח (0=שני עד
    6=ראשון, נוצרות אוטומטית - ראו ResourceCalendar._l10n_il_ensure_shift_weekdays),
    כל אחת עם בחירת המשמרת של אותו יום."""
    _name = "mdl.attendance.shift.weekday"
    _description = "יום בשבוע - לוח משמרות"
    _order = "dayofweek"

    calendar_id = fields.Many2one("resource.calendar", required=True, ondelete="cascade")
    dayofweek = fields.Selection(
        [("0", "שני"), ("1", "שלישי"), ("2", "רביעי"), ("3", "חמישי"), ("4", "שישי"), ("5", "שבת"), ("6", "ראשון")],
        string="יום", required=True,
    )
    l10n_il_shift_choice = fields.Selection(
        [("off", "לא עובד"), ("morning", "משמרת בוקר"), ("afternoon", "משמרת ערב"), ("any", "משמרת (בוקר או ערב)")],
        string="משמרת", required=True, default="off",
    )

    _calendar_dayofweek_uniq = models.Constraint(
        "unique(calendar_id, dayofweek)", "יום כפול באותו לוח משמרות.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.calendar_id._l10n_il_sync_shift_weekdays()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "l10n_il_shift_choice" in vals:
            self.calendar_id._l10n_il_sync_shift_weekdays()
        return res


class ResourceCalendarAttendance(models.Model):
    _inherit = "resource.calendar.attendance"

    # --- נוכחות + יומי בלבד: בחירה לכל יום - שעות ישירות, או כפולה של
    # l10n_il_daily_base_hours ("יומיות"). לא רלוונטי לשעתי (hour_from/
    # hour_to משמשים שם ישירות כרגיל) ולא למשמרות (attendance_ids נגזרות
    # אוטומטית שם - ראו ResourceCalendar._l10n_il_sync_shift_weekdays). ---
    l10n_il_day_kind = fields.Selection(
        [("hours", "שעות"), ("daily_units", "יומיות")], string="הגדרת היום לפי",
    )
    l10n_il_day_hours = fields.Float(string="שעות", help="מספר שעות ישיר ליום הזה.")
    l10n_il_day_units = fields.Selection(
        [("1", "יומית"), ("1.5", "יומית וחצי"), ("2", "שני יומיות"), ("2.5", "שני יומיות וחצי"), ("3", "שלוש יומיות")],
        string="יומיות",
        help="כפולה של 'שעות ליומית אחת' שהוגדר ברמת הלוח.",
    )
    l10n_il_day_total_hours = fields.Float(
        string="סה\"כ שעות ליום", compute="_compute_l10n_il_day_total_hours", store=True,
    )

    @api.depends("l10n_il_day_kind", "l10n_il_day_hours", "l10n_il_day_units", "calendar_id.l10n_il_daily_base_hours")
    def _compute_l10n_il_day_total_hours(self):
        for line in self:
            if line.l10n_il_day_kind == "hours":
                line.l10n_il_day_total_hours = line.l10n_il_day_hours
            elif line.l10n_il_day_kind == "daily_units" and line.l10n_il_day_units:
                line.l10n_il_day_total_hours = float(line.l10n_il_day_units) * (line.calendar_id.l10n_il_daily_base_hours or 0.0)
            else:
                line.l10n_il_day_total_hours = 0.0

    @api.constrains("l10n_il_day_total_hours")
    def _check_l10n_il_day_total_hours(self):
        for line in self:
            if (
                line.calendar_id.l10n_il_schedule_type == "attendance"
                and line.calendar_id.l10n_il_counting_type == "daily"
                and line.l10n_il_day_total_hours > 24
            ):
                raise ValidationError(
                    "סה\"כ השעות ליום (%.2f) חורג מ-24 שעות ביום - יש לתקן." % line.l10n_il_day_total_hours
                )

    def _l10n_il_sync_day_hour_range(self):
        """מרכז את hour_from/hour_to סביב 12:00 לפי l10n_il_day_total_hours -
        אין באמת שעת התחלה/סיום במצב 'יומי' (רק סה"כ שעות), אבל
        hour_from/hour_to הילידיים עדיין דרושים למנגנוני הליבה (בדיוק
        הטכניקה של duration_based/duration_hours הילידי, ראו
        resource_calendar_attendance.py._inverse_duration_hours).

        רק לשורות שכבר קיבלו l10n_il_day_kind בפועל - שורות ברירת המחדל
        שהילידי יוצר אוטומטית (5 ימי עבודה סטנדרטיים) עדיין לא הוגדרו
        כ"יומי" ע"י המשתמש, ואסור לגעת ב-hour_from/hour_to שלהן (בעבר זה
        אילץ את כולן ל-12:00-12:00 בו-זמנית וגרם ל'Attendances can't
        overlap' על יצירת לוח חדש)."""
        for line in self:
            if (
                line.l10n_il_day_kind
                and line.calendar_id.l10n_il_schedule_type == "attendance"
                and line.calendar_id.l10n_il_counting_type == "daily"
            ):
                hours = line.l10n_il_day_total_hours
                line.hour_from = 12 - hours / 2
                line.hour_to = 12 + hours / 2

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._l10n_il_sync_day_hour_range()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {"l10n_il_day_kind", "l10n_il_day_hours", "l10n_il_day_units"} & set(vals):
            self._l10n_il_sync_day_hour_range()
        return res

    @api.constrains("work_entry_type_id", "calendar_id")
    def _check_l10n_il_work_entry_type_matches_schedule_type(self):
        shift_types = self.env["hr.work.entry.type"]
        for xmlid in (
            "mdl_attendances.work_entry_type_morning_attendance",
            "mdl_attendances.work_entry_type_afternoon_attendance",
            "mdl_attendances.work_entry_type_morning_weekend_attendance",
            "mdl_attendances.work_entry_type_afternoon_weekend_attendance",
        ):
            work_entry_type = self.env.ref(xmlid, raise_if_not_found=False)
            if work_entry_type:
                shift_types |= work_entry_type
        attendance_type = self.env.ref("hr_work_entry.work_entry_type_attendance", raise_if_not_found=False)
        for line in self:
            if not line.work_entry_type_id or not line.calendar_id:
                continue
            schedule_type = line.calendar_id.l10n_il_schedule_type
            if schedule_type == "attendance" and line.work_entry_type_id in shift_types:
                raise ValidationError(
                    "לא ניתן לבחור סוג כניסת עבודה של משמרת (בוקר/ערב) בלוח זמנים מסוג 'נוכחות'."
                )
            if schedule_type == "shifts" and attendance_type and line.work_entry_type_id == attendance_type:
                raise ValidationError(
                    "לא ניתן לבחור סוג כניסת עבודה 'נוכחות' בלוח זמנים מסוג 'משמרות' - יש לבחור משמרת בוקר/ערב."
                )
