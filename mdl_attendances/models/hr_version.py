from datetime import date, datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_BOUNDARY_EPSILON = timedelta(seconds=1)

# משמרת (בוקר או ערב) = יום עבודה מלא, תמיד 9.5 שעות משולמות - לא משנה כמה
# זמן העובד באמת עבד/נשאר (אין יותר עיגול-דקות למול השעון בפועל). ראו
# resource_calendar.py._get_hours_per_day, שמייבא את הקבוע הזה כדי שהממוצע
# היומי המוצג בלוח הזמנים יתאים (9.5, לא סכום נאיבי של בוקר+ערב=24).
L10N_IL_SHIFT_STANDARD_HOURS = 9.5

# חלק ממשמרת ערב הוא שינה (01:30-06:30 קבועות, לא תלויות בשעת הכניסה
# בפועל) - העובד לא עובד ולא משולם על הפרק הזה. 9.5 (עבודה) + 5.0 (שינה)
# = 14.5, בדיוק סך שעות משמרת הערב כפי שמופיע בקובץ מערכת השכר של הלקוח.
L10N_IL_SLEEP_HOURS = 5.0


def _l10n_il_round_half_hour(dt, direction):
    """מעגל dt (naive UTC, שקול למקומי בקונבנציית הפרויקט) ל-30 הדקות
    הקרובות: 'down' - למטה (כניסה), 'up' - למעלה (יציאה). בשימוש כיום רק
    לקטעי שעות נוספות (OVERTIME) - משמרות עצמן (בוקר/ערב) כבר לא מתעגלות
    למול השעון בפועל, הן תמיד יוצאות 9.5 שעות קבועות (ראו
    L10N_IL_SHIFT_STANDARD_HOURS למעלה).

    סובלנות של שנייה סביב גבול חצי-שעה: מנוע השעות הנוספות מוסיף אפסילון
    זעיר לנקודת הפיצול (16:00:00.000120) - בלי הסובלנות, "up" היה מעגל את
    זה חצי שעה מיותרת וגורם לכפל-ספירה מול השעות הנוספות."""
    floor_dt = dt - timedelta(minutes=dt.minute % 30, seconds=dt.second, microseconds=dt.microsecond)
    if direction == "down":
        return floor_dt
    if dt - floor_dt <= _BOUNDARY_EPSILON:
        return floor_dt
    return floor_dt + timedelta(minutes=30)


class HrVersion(models.Model):
    _inherit = "hr.version"

    # קובע אילו לוחות זמנים (resource.calendar) ניתן לבחור לעובד הזה - ראו
    # ה-domain על resource_calendar_id ב-hr_employee_views.xml, ואת
    # ה-constraint למטה שאוכף את זה גם בכתיבה ישירה (למשל import/API).
    l10n_il_employee_schedule_type = fields.Selection(
        [("attendance", "נוכחות"), ("shifts", "משמרות")],
        string="סוג נוכחות עובד", default="attendance", required=True,
        help="נוכחות/משמרות - קובע אילו לוחות זמנים ניתן לבחור לעובד (ראו "
             "resource.calendar.l10n_il_schedule_type).",
    )

    # רלוונטי לעובד שאינו עובד משמרות (כל שלושת סוגי השכר - חודשי/יומי/
    # שעתי-אמיתי): איך מתייחסים ליום שאין בו לא נוכחות ולא חופשה/מחלה
    # מאושרת ב-Time Off (לא "יום חסר" שיש לו כיסוי כלשהו - יום שבאמת אין
    # עליו שום מידע). יום כזה מקבל רשומת עבודה אמיתית מסוג "העדרות"
    # (IL_ABSENCE, ראו hr_work_entry_type_data.xml + _l10n_il_create_absence_entries
    # למטה) - לא נספר "בשקט" בלי רשומה. גם כאן זה "יום" מבחינה עסקית, אבל
    # החישוב בפועל הוא לפי שעות (duration=hours_per_day) - ראו
    # hr_payslip_worked_days.py._compute_amount.
    l10n_il_missing_days_policy = fields.Selection(
        [("no_payment", "ללא תשלום"), ("daily_payment", "תשלום יומי"), ("other", "תשלום אחר")],
        string="טיפול בימים חסרים", default="no_payment", required=True,
        help="ללא תשלום: שווה 0. תשלום יומי: שווה יום עבודה מלא (שכר יומי "
             "מחושב). תשלום אחר: אחוז משכר יומי, או סכום קבוע ליום - ראו "
             "l10n_il_missing_days_other_kind.",
    )
    l10n_il_missing_days_other_kind = fields.Selection(
        [("percentage", "אחוז"), ("amount", "סכום")],
        string="סוג תשלום אחר",
        help="אחוז: אחוז משכר היום המחושב. סכום: סכום קבוע ליום, בלי קשר "
             "לשכר היומי.",
    )
    l10n_il_missing_days_other_percentage = fields.Float(
        string="אחוז מהיומי", help="לדוגמה 50 = חצי משכר היום המחושב.",
    )
    l10n_il_missing_days_other_amount = fields.Monetary(
        string="סכום קבוע ליום",
    )

    @api.constrains("resource_calendar_id", "l10n_il_employee_schedule_type")
    def _check_l10n_il_employee_schedule_type(self):
        for version in self:
            calendar = version.resource_calendar_id
            if calendar and calendar.l10n_il_schedule_type != version.l10n_il_employee_schedule_type:
                raise ValidationError(
                    "לוח הזמנים שנבחר (%s) אינו תואם את סוג הנוכחות של העובד (%s)."
                    % (calendar.display_name, dict(version._fields["l10n_il_employee_schedule_type"].selection)[version.l10n_il_employee_schedule_type])
                )

    def _l10n_il_shift_type_ids(self):
        """מזהי סוגי רשומות העבודה של משמרות (בוקר/ערב חול, לפי הלוח של
        הגרסה הזאת אם קיימת - אחרת ברירת המחדל הגלובלית; + חול/סופ"ש, שלא
        ניתנים להתאמה אישית)."""
        ids_ = set()
        calendar = self.resource_calendar_id if self else None
        morning = (calendar and calendar.l10n_il_shift_morning_type_id) or self.env.ref(
            "mdl_attendances.work_entry_type_morning_attendance", raise_if_not_found=False)
        afternoon = (calendar and calendar.l10n_il_shift_afternoon_type_id) or self.env.ref(
            "mdl_attendances.work_entry_type_afternoon_attendance", raise_if_not_found=False)
        if morning:
            ids_.add(morning.id)
        if afternoon:
            ids_.add(afternoon.id)
        for xmlid in (
            "mdl_attendances.work_entry_type_morning_weekend_attendance",
            "mdl_attendances.work_entry_type_afternoon_weekend_attendance",
        ):
            rec = self.env.ref(xmlid, raise_if_not_found=False)
            if rec:
                ids_.add(rec.id)
        return ids_

    def _get_real_attendance_work_entry_vals(self, intervals):
        """סיווג נוכחות למשמרת בוקר/ערב (+סופ"ש) לעובד משמרות: משך רשומת
        העבודה נשאר המשך *האמיתי* של הנוכחות (לא נכפה יותר לקבוע כלשהו) -
        "יום קצר = יום מלא" מתבצע דרך המנגנון המובנה של אודו
        (hr.work.entry.type.round_days='FULL'/round_days_type='UP', ראו
        hr_work_entry_type_data.xml + hr_payslip_worked_days.py, שמשתמש ב-
        hr.payslip.worked_days.number_of_days המחושב-אוטומטית), לא ע"י
        עיוות משך הרשומה בקוד. שעות מעבר לשעות המשמרת המתוכננות בלוח כבר
        לא מגיעות לכאן בכלל - מנוע השעות הנוספות הילידי (hr.attendance.
        overtime.rule) מפריד אותן ל-OVERTIME נפרדת *לפני* יצירת הרשומה הזאת
        (ראו hr_work_entry_attendance._get_attendance_intervals) - כך שיום
        לעולם לא "יתעגל" ליותר מ-1.0 בגלל עבודה מעבר לשעות.

        משמרת ערב מוסיפה רשומת "שינה" נפרדת ולא-משולמת - 5 השעות *האחרונות*
        של המשמרת האמיתית (לא הפרש קבוע מההתחלה), כך שגם משמרת קצרה עדיין
        "מוותרת" על 5 שעות שינה לפני שנשאר לה מה לעגל ליום. hr.attendance
        עצמה (השעון הגולמי) לא נוגעים בה בכלל - רק ה-work entries הנגזרים
        ממנה.

        עובד שאינו עובד משמרות (הלוח שלו לא מסוג משמרות, _classify_check_in
        מחזיר False): נשאר בסוג רשומת הנוכחות הגנרי, עם אותו עיקרון בדיוק -
        משך אמיתי, "יום קצר=יום מלא" ע"י round_days על הסוג הגנרי (הוגדר גם
        הוא ל-FULL/UP ב-hr_work_entry_type_data.xml).

        אם עובד ביצע יותר מכניסה אחת (משמרת בוקר+ערב, שתי כניסות באותו יום,
        או הפסקת צהריים) באותו יום מקומי, רק הכניסה המוקדמת ביום נחשבת "יום
        עבודה" (מתעגלת ומשולמת) - יום עבודה נספר פעם אחת בלבד; הכניסות
        הנוספות נשארות "נוכחות" גנרית (רשומת מידע גולמית, לא משולמת).

        קטעי שעות נוספות (OVERTIME, שמנוע השעות הנוספות פיצל בגבול 16:00/
        06:30) ממשיכים להתעגל לחצי שעה כרגיל - הן עדיין לא משולמות בפועל
        (ראו rule_ilm/ilh_ot_attendance ב-hr_salary_rule_data.xml, מאופסות
        זמנית לפי בקשת הלקוח)."""
        vals = super()._get_real_attendance_work_entry_vals(intervals)
        generic_type = self.env.ref("hr_work_entry.work_entry_type_attendance", raise_if_not_found=False)
        overtime_type = self.env.ref("hr_work_entry.work_entry_type_overtime", raise_if_not_found=False)
        if not generic_type:
            return vals
        calendar = self.resource_calendar_id
        # בוקר/ערב נלקחים מהלוח של הגרסה הזאת (ניתן להתאמה אישית ללוח -
        # ראו resource_calendar.py.l10n_il_shift_morning_type_id/afternoon_type_id);
        # חול/סופ"ש עדיין קבועים - הספק לא ביקש להתאים אותם אישית.
        type_by_attendance_type = {
            "morning": calendar.l10n_il_shift_morning_type_id.id,
            "afternoon": calendar.l10n_il_shift_afternoon_type_id.id,
            "morning_weekend": self.env.ref("mdl_attendances.work_entry_type_morning_weekend_attendance").id,
            "afternoon_weekend": self.env.ref("mdl_attendances.work_entry_type_afternoon_weekend_attendance").id,
        }
        sleep_type = self.env.ref("mdl_attendances.work_entry_type_sleep", raise_if_not_found=False)
        attendance_ids = {
            v["attendance_id"] for v in vals
            if v.get("work_entry_type_id") == generic_type.id and v.get("attendance_id")
        }
        attendances = self.env["hr.attendance"].sudo().browse(attendance_ids)
        attendance_info_by_id = {}
        for att in attendances:
            period = att._classify_check_in(att.employee_id, att.check_in)
            full_period = period
            if period and att._is_l10n_il_weekend_check_in(att.employee_id, att.check_in):
                full_period = f"{period}_weekend"
            # False (לא לוח משמרות) -> "plain": יום עבודה רגיל, מתעגל
            # ל-calendar.hours_per_day במקום סיווג בוקר/ערב - ראו למטה.
            attendance_info_by_id[att.id] = (full_period or "plain", att.employee_id)

        # יום אחד = כניסה אחת לכל היותר (משמרת או יום רגיל): מזהים, לכל
        # (עובד, תאריך מקומי), רק את הכניסה הכרונולוגית המוקדמת ביותר
        # כ"ראשית" - רק היא תמיר לרשומת יום-עבודה משולמת; כניסה נוספת של
        # אותו עובד באותו יום נשארת נוכחות גנרית (לא נספרת כיום נוסף).
        shift_candidates = [
            v for v in vals
            if v.get("work_entry_type_id") == generic_type.id
            and v.get("attendance_id") in attendance_info_by_id
        ]
        primary_attendance_ids = set()
        seen_days = set()
        for v in sorted(shift_candidates, key=lambda v: v["date_start"]):
            employee = attendance_info_by_id[v["attendance_id"]][1]
            tz = self.env["hr.attendance"]._get_tz_for_employee(employee)
            local_date = pytz.utc.localize(v["date_start"]).astimezone(tz).date()
            key = (employee.id, local_date)
            if key in seen_days:
                continue
            seen_days.add(key)
            primary_attendance_ids.add(v["attendance_id"])

        extra_vals = []
        for v in vals:
            if not v.get("date_start") or not v.get("date_stop"):
                continue
            if overtime_type and v.get("work_entry_type_id") == overtime_type.id:
                v["date_start"] = _l10n_il_round_half_hour(v["date_start"], "down")
                v["date_stop"] = _l10n_il_round_half_hour(v["date_stop"], "up")
                continue
            if v.get("work_entry_type_id") != generic_type.id or not v.get("attendance_id"):
                continue
            if v["attendance_id"] not in primary_attendance_ids:
                continue
            att_type, employee = attendance_info_by_id[v["attendance_id"]]
            if att_type == "plain":
                # עובד לא-משמרות: נשאר בסוג רשומת הנוכחות הגנרי, עם המשך
                # (=שעות) האמיתי כפי שהוא - "יום קצר = יום מלא" מתבצע עכשיו
                # ע"י round_days/round_days_type על סוג רשומת העבודה עצמו
                # (ראו hr_work_entry_type_data.xml + hr_payslip_worked_days.py),
                # לא ע"י כפיית משך כאן. אם העובד עבד יותר משעות המשמרת
                # המתוכננות בלוח, מנוע השעות הנוספות הילידי כבר הפריד את
                # העודף לרשומת OVERTIME נפרדת *לפני* שהגענו לכאן (ראו
                # hr_work_entry_attendance._get_attendance_intervals) - כך
                # ש"יום" לעולם לא מתעגל ליותר מ-1.0 בגלל שעות נוספות.
                continue
            v["work_entry_type_id"] = type_by_attendance_type[att_type]
            if att_type.startswith("afternoon") and sleep_type:
                # שינה = 5 השעות *האחרונות* של המשמרת האמיתית (כבר לאחר
                # שהעודף מעבר ללוח הוצא כ-OVERTIME על ידי המנוע הילידי) -
                # לא הפרש קבוע מתחילת המשמרת. משך רשומת "משמרת ערב" עצמה
                # לא נכפה יותר (היה date_start+9.5 קבוע) - היא פשוט המשמרת
                # האמיתית פחות 5 שעות השינה, ומתעגלת ל"יום" ע"י round_days
                # (ראו למעלה). אם המשמרת האמיתית קצרה מ-5 שעות (קצה קיצוני),
                # משך השינה מוגבל למשמרת עצמה כדי לא לרדת מתחת ל-date_start.
                #
                # date+duration ישירות (לא רק date_start/date_stop): שינה
                # מתחילה בפועל אחרי חצות (למשל 01:00) - אם היינו משאירים
                # ל-postprocess הילידי לגזור את התאריך מ-date_start שלה
                # (start_utc.astimezone(tz).date()), הוא היה מיוחס בטעות
                # ליום הבא (לא ליום תחילת המשמרת, כמו כל שאר הרשומה). לכן
                # קובעים כאן את date במפורש מ-date_start ה*מקורי* של המשמרת
                # עצמה (v["date_start"], שתמיד לפני חצות) - ראו גם הטיפול
                # הייעודי ב-_generate_work_entries_postprocess שמכבד date
                # שכבר נקבע במקום לגזור אותו מחדש. date_start/date_stop עדיין
                # נשלחים (לא רק date/duration) כי _get_work_entries_values
                # הילידי קורא אותם על כל הרשימה הגולמית עוד *לפני*
                # שה-postprocess רץ בכלל (למעקב טווח תאריכי הגרסה) - הם
                # מוסרים שם לפני שהם יכולים להשפיע על date/duration.
                real_stop = v["date_stop"]
                sleep_hours = min(L10N_IL_SLEEP_HOURS, (real_stop - v["date_start"]).total_seconds() / 3600.0)
                sleep_start = real_stop - timedelta(hours=sleep_hours)
                shift_date = pytz.utc.localize(v["date_start"]).astimezone(
                    self.env["hr.attendance"]._get_tz_for_employee(employee)
                ).date()
                v["date_stop"] = sleep_start
                extra_vals.append({
                    "name": "%s: %s" % (sleep_type.name, employee.name),
                    "date": shift_date,
                    "duration": sleep_hours,
                    "date_start": sleep_start,
                    "date_stop": real_stop,
                    "work_entry_type_id": sleep_type.id,
                    "employee_id": employee.id,
                    "version_id": v["version_id"],
                    "company_id": v.get("company_id"),
                    "attendance_id": v.get("attendance_id"),
                })
        vals.extend(extra_vals)
        return vals

    @api.model
    def _generate_work_entries_postprocess(self, vals_list):
        """משמרת ערב (16:00 -> 06:30 למחרת) שייכת *כולה* ליום שבו התחילה -
        בדיוק כמו בקובץ מערכת השכר (שורת נוכחות אחת, 14.5 שעות, על תאריך
        תחילת המשמרת), ולא מפוצלת בחצות לשתי רשומות (8+6.5) כמו שהמנגנון
        הילידי עושה. לכן כאן, לפני המנגנון הילידי, ממירים כל vals מסוג משמרת
        מטווח datetime ל-date (תאריך ההתחלה המקומי) + duration (אורך הטווח
        המלא) - פורמט שהמנגנון הילידי מקבל כמות-שהוא ללא פיצול. קריטי במיוחד
        בגבול חודש: משמרת ערב של ה-30 בחודש נספרת כולה באותו חודש, כמו בקובץ.

        שעות נוספות (OVERTIME): משך כל קטע מעוגל כלפי מעלה לחצי שעה - שקול
        לעיגול היציאה מעלה בקובץ (הקטע מתחיל בדיוק בגבול המשמרת 16:00/06:30,
        כך ש"משך מעוגל מעלה" == "יציאה מעוגלת מעלה פחות הגבול"). סובלנות של
        שנייה כדי שקטע שכבר בדיוק על חצי שעה לא יקפוץ חצי שעה מיותרת."""
        overtime_type = self.env.ref("hr_work_entry.work_entry_type_overtime", raise_if_not_found=False)
        overtime_type_id = overtime_type.id if overtime_type else None
        # shift_type_ids תלוי בלוח של כל גרסה בנפרד (סוג רשומת בוקר/ערב
        # ניתן להתאמה אישית ללוח - ראו resource_calendar.py) - לכן מחושב
        # פר-version_id (עם cache), לא פעם אחת גלובלית כמו קודם. self כאן
        # הוא recordset ריק (@api.model) - _l10n_il_shift_type_ids נקרא על
        # רשומת hr.version קונקרטית לכל version_id שנמצא ב-vals_list.
        shift_type_ids_by_version = {}

        def _shift_type_ids(version_id):
            if version_id not in shift_type_ids_by_version:
                version = self.env["hr.version"].browse(version_id)
                shift_type_ids_by_version[version_id] = version._l10n_il_shift_type_ids()
            return shift_type_ids_by_version[version_id]

        def _ceil_half_hour(hours):
            import math
            return math.ceil((hours - 1.0 / 3600.0) / 0.5) * 0.5

        for vals in vals_list:
            if overtime_type_id and vals.get("work_entry_type_id") == overtime_type_id:
                if vals.get("date_start") and vals.get("date_stop"):
                    span = (vals["date_stop"] - vals["date_start"]).total_seconds() / 3600.0
                    vals["date"] = vals["date_start"].date()
                    vals["duration"] = _ceil_half_hour(span)
                    vals.pop("date_start", None)
                    vals.pop("date_stop", None)
                elif vals.get("duration"):
                    vals["duration"] = _ceil_half_hour(vals["duration"])
                continue
            if "date" in vals and "duration" in vals:
                # date/duration כבר נקבעו במפורש למעלה (ראו רשומת "שינה" ב-
                # _get_real_attendance_work_entry_vals) - date_start/date_stop
                # קיימים רק בשביל _get_work_entries_values הילידי (רץ לפני
                # ה-postprocess), ואסור לתת למנגנון הילידי לגזור מהם מחדש את
                # ה-date (start_utc.astimezone(tz).date() היה נותן תאריך שגוי
                # כאן - זמן ההתחלה האמיתי של השינה הוא אחרי חצות).
                vals.pop("date_start", None)
                vals.pop("date_stop", None)
                continue
            if (
                vals.get("version_id")
                and vals.get("work_entry_type_id") in _shift_type_ids(vals["version_id"])
                and vals.get("date_start") and vals.get("date_stop")
            ):
                version = self.env["hr.version"].browse(vals["version_id"])
                tz_name = (
                    version.resource_calendar_id.tz
                    or version.employee_id.resource_calendar_id.tz
                    or version.company_id.resource_calendar_id.tz
                    or "UTC"
                )
                tz = pytz.timezone(tz_name)
                start = vals["date_start"]
                start_utc = start if start.tzinfo else pytz.UTC.localize(start)
                stop = vals["date_stop"]
                stop_utc = stop if stop.tzinfo else pytz.UTC.localize(stop)
                vals["date"] = start_utc.astimezone(tz).date()
                vals["duration"] = round((stop_utc - start_utc).total_seconds()) / 3600
                vals.pop("date_start", None)
                vals.pop("date_stop", None)
        return super()._generate_work_entries_postprocess(vals_list)

    def _generate_work_entries(self, date_start, date_stop, force=False):
        new_entries = super()._generate_work_entries(date_start, date_stop, force=force)
        self._l10n_il_create_absence_entries(date_start, date_stop)
        return new_entries

    def _l10n_il_create_absence_entries(self, date_start, date_stop):
        """יוצר רשומת עבודה אמיתית מסוג "העדרות" (IL_ABSENCE) לכל יום עבודה
        צפוי (לפי הימים המוגדרים בלוח, resource.calendar.attendance.dayofweek)
        שאין לו שום work entry בכלל - לא נוכחות, לא חופשה/מחלה מאושרת
        ב-Time Off (שיוצרת work entry משלה, ולכן "מכסה" את היום ולא נחשבת
        חסרה). רק לעובד שאינו עובד משמרות - עובד משמרות ממשיך להשתמש
        במנגנון היום-משמרת הקיים (ראו hr_payslip_worked_days.py). התשלום
        על "העדרות" נקבע לפי l10n_il_missing_days_policy - שם.

        רץ *אחרי* שהרשומות האמיתיות כבר נוצרו (שאילתה על מה שבאמת קיים
        ב-DB), לא כחלק מצינור ה-vals הפנימי - הרבה יותר פשוט ובטוח מלהתערב
        בפורמט הגולמי (אין צורך ב-date_start/date_stop דמה, ה-ORM כבר יודע
        ליצור hr.work.entry ישירות מ-date+duration).

        בטיחות: לעולם לא יוצר "העדרות" עבור תאריך שעדיין לא הגיע (עד
        אתמול בלבד) - אחרת ה-cron היומי (שמייצר מראש את כל החודש הנוכחי,
        ראו hr_work_entry._cron_generate_missing_work_entries) היה מסמן
        ימים עתידיים כ"נעדר" עוד לפני שהיה להם סיכוי לקרות. אידמפוטנטי -
        קריאה חוזרת לא יוצרת כפילויות (בודקת מול מה שכבר קיים בפועל)."""
        absence_type = self.env.ref("mdl_attendances.work_entry_type_absence", raise_if_not_found=False)
        if not absence_type:
            return
        range_start = date_start.date() if isinstance(date_start, datetime) else date_start
        range_stop = date_stop.date() if isinstance(date_stop, datetime) else date_stop
        range_stop = min(range_stop, date.today() - timedelta(days=1))
        if range_start > range_stop:
            return
        to_create = []
        for version in self.filtered(lambda v: v.l10n_il_employee_schedule_type != "shifts" and v.contract_date_start):
            calendar = version.resource_calendar_id
            if not calendar:
                continue
            workdays = set(calendar.attendance_ids.mapped("dayofweek"))
            if not workdays:
                continue
            d = max(range_start, version.contract_date_start)
            end = range_stop
            if version.date_end:
                end = min(end, version.date_end)
            if d > end:
                continue
            existing = set(self.env["hr.work.entry"].search([
                ("version_id", "=", version.id),
                ("date", ">=", d), ("date", "<=", end),
                ("state", "in", ("draft", "validated")),
            ]).mapped("date"))
            while d <= end:
                if str(d.weekday()) in workdays and d not in existing:
                    to_create.append({
                        "name": "%s: %s" % (absence_type.name, version.employee_id.name),
                        "date": d,
                        "duration": calendar.hours_per_day or 0.0,
                        "work_entry_type_id": absence_type.id,
                        "employee_id": version.employee_id.id,
                        "version_id": version.id,
                        "company_id": version.company_id.id,
                    })
                d += timedelta(days=1)
        if to_create:
            self.env["hr.work.entry"].create(to_create)
