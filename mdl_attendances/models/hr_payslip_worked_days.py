from odoo import api, models

# code -> (period, is_weekend) - לזיהוי שורות worked-days של משמרות
L10N_IL_SHIFT_CODE_INFO = {
    "IL_ATT_MORNING": ("morning", False),
    "IL_ATT_AFTERNOON": ("afternoon", False),
    "IL_ATT_MORNING_WEEKEND": ("morning", True),
    "IL_ATT_AFTERNOON_WEEKEND": ("afternoon", True),
}


class HrPayslipWorkedDays(models.Model):
    _inherit = "hr.payslip.worked_days"

    def _l10n_il_days_count(self):
        """מספר ימי עבודה בפועל = מספר רשומות העבודה מהסוג הזה עם משך חיובי
        בתקופת התלוש - לא round_days/number_of_days הילידי: הילידי (ראו
        hr_payslip._get_worked_day_lines_values) מסכם קודם את *כל* השעות של
        הסוג הזה לאורך כל התלוש ומעגל פעם אחת בסוף - round(sum(hours))
        ולא sum(round(hours)) - כך שכמה ימים קצרים "מתקזזים" זה עם זה
        באיחוד (למשל 22 ימים שכל אחד ~9.07 שעות בפועל נותנים סה"כ 199.5,
        199.5/9.5=21.0 בדיוק - יום אחד "אבד" בעיגול, למרות שכל 22 הימים
        בפועל התרחשו). round_days על סוג רשומת העבודה (ראו
        hr_work_entry_type_data.xml) עדיין מוגדר ל-FULL/UP - נכון סמנטית
        ושימושי לתכונות ילידיות אחרות (למשל דוחות/איזון חופשה) - אבל לא
        לחישוב השכר כאן, שדורש עיגול *לכל יום בנפרד* לפני הסכימה, לא אחריה."""
        self.ensure_one()
        slip = self.payslip_id
        return self.env["hr.work.entry"].search_count([
            ("employee_id", "=", slip.employee_id.id),
            ("date", ">=", slip.date_from),
            ("date", "<=", slip.date_to),
            ("work_entry_type_id", "=", self.work_entry_type_id.id),
            ("duration", ">", 0),
            ("state", "in", ("draft", "validated")),
        ])

    @api.depends(
        "payslip_id.version_id.l10n_il_daily_wage",
        "payslip_id.version_id.l10n_il_weekend_daily_wage",
        "payslip_id.version_id.resource_calendar_id",
        "payslip_id.version_id.l10n_il_missing_days_policy",
        "payslip_id.version_id.l10n_il_missing_days_other_kind",
        "payslip_id.version_id.l10n_il_missing_days_other_percentage",
        "payslip_id.version_id.l10n_il_missing_days_other_amount",
        "payslip_id.version_id.l10n_il_hourly_kind",
        "number_of_hours",
    )
    def _compute_amount(self):
        """שכר יומי לפי ימים, לא לפי שעות - בדיוק כלל הלקוח (קובץ מערכת השכר,
        "העברות לבנק": שכר = ימי עבודה x תעריף יומי): כל יום שבו העובד הגיע
        נספר יום אחד מלא ומשולם תעריף יומי מלא, גם יום קצר, גם משמרת ערב
        ארוכה - היום הוא היחידה, לא השעה. "ימים" נספרים כאן דרך
        _l10n_il_days_count (ספירת רשומות עם משך חיובי) ולא דרך
        number_of_days הילידי - ראו הסבר שם.

        לעובד יומי-משמרות (wage_type='hourly', עובד משמרות): סכום השורה =
        תעריף יומי x number_of_days; יום שישי/שבת משתמש בתעריף שישי/שבת אם
        הוגדר (אחרת בתעריף חול). דורס את החישוב הילידי (ששם משתמש בשעות
        *בפועל*, לא בימים מעוגלים - לא מבטיח "יום קצר=יום מלא").

        לעובד גלובלי (חודשי) עובד-משמרות: החישוב הילידי (פריסת השכר הגלובלי
        על השעות) נשאר, ובנוסף ימי שישי/שבת מקבלים תוספת של תעריף שישי/שבת
        x number_of_days - בדיוק נוסחת הקובץ לעובד "גלובלי + שבת"
        (10000 + 4 x 400).

        "העדרות" (IL_ABSENCE, יום שאין לו נוכחות/חופשה/מחלה מאושרת בכלל -
        נוצרת אוטומטית ב-hr_version.py._l10n_il_create_absence_entries, רק
        לעובד שאינו עובד משמרות): התשלום נקבע לפי l10n_il_missing_days_policy -
        "ללא תשלום" (0), "תשלום יומי" (מלא, כמו יום עבודה רגיל - hourly_wage),
        או "תשלום אחר" (אחוז משכר השעה המחושב, או סכום קבוע ליום מומר לשקילות
        שעתית). "זה יום אבל החישוב בפועל לפי שעות" - הרשומה עצמה תמיד
        duration=hours_per_day, והתשלום הוא rate_per_hour x number_of_hours
        (לא סכום-ליום ישיר) - עקבי עם שאר המודל.

        עובד שאינו עובד משמרות, לא "העדרות" (l10n_il_employee_schedule_type
        != 'shifts'): שעתי-אמיתי (l10n_il_hourly_kind=='true_hourly') לא
        נוגעים בכלל - החישוב הילידי (hourly_wage x number_of_hours) כבר
        בדיוק מה שצריך, בלי עיגול ליום. אחרת (חודשי, או יומי-טכני
        לא-משמרות): l10n_il_computed_daily_wage x number_of_days (ולא
        חישוב-ילידי לחודשי, ששם מחלק את wage במספר השעות *בפועל* באותו
        תלוש - נוסחה שמנרמלת את עצמה תמיד לסך המלא של wage)."""
        super()._compute_amount()
        for worked_days in self:
            info = L10N_IL_SHIFT_CODE_INFO.get(worked_days.code)
            slip = worked_days.payslip_id
            if slip.edited or slip.state != "draft":
                continue
            version = slip.version_id
            if not version:
                continue
            amount_rate = worked_days.work_entry_type_id.amount_rate

            if info and worked_days.is_paid:
                period, is_weekend = info
                days = worked_days._l10n_il_days_count()
                if slip.wage_type == "hourly":
                    daily_wage = (is_weekend and version.l10n_il_weekend_daily_wage) or version.l10n_il_daily_wage
                    if not daily_wage:
                        continue
                    worked_days.amount = daily_wage * days * amount_rate
                elif is_weekend and version.l10n_il_weekend_daily_wage:
                    worked_days.amount = worked_days.amount + version.l10n_il_weekend_daily_wage * days
                continue

            if worked_days.code == "IL_ABSENCE":
                policy = version.l10n_il_missing_days_policy
                if policy == "no_payment":
                    rate_per_hour = 0.0
                elif policy == "daily_payment":
                    rate_per_hour = version.hourly_wage
                elif version.l10n_il_missing_days_other_kind == "percentage":
                    rate_per_hour = version.hourly_wage * (version.l10n_il_missing_days_other_percentage or 0.0) / 100.0
                else:  # "amount" - סכום קבוע ליום, מומר לשקילות שעתית
                    hours_per_day = version.resource_calendar_id.hours_per_day
                    rate_per_hour = (version.l10n_il_missing_days_other_amount / hours_per_day) if hours_per_day else 0.0
                worked_days.amount = rate_per_hour * worked_days.number_of_hours * amount_rate
                continue

            if version.l10n_il_hourly_kind == "true_hourly":
                # שעתי-אמיתי: לא נוגעים בכלל - החישוב הילידי (hourly_wage x
                # number_of_hours, ראו hr_payroll hr_payslip_worked_days.py)
                # כבר בדיוק מה שצריך - בלי עיגול ליום, לפי שעות בפועל.
                continue

            if not info and worked_days.is_paid and version.l10n_il_employee_schedule_type != "shifts":
                # l10n_il_computed_daily_wage כבר שווה בדיוק ל-l10n_il_daily_wage
                # כש-wage_type=='hourly' (ראו l10n_il_hr_payroll
                # hr_version.py._compute_l10n_il_wage_bases) - שדה אחד תקף
                # לשני סוגי השכר.
                days = worked_days._l10n_il_days_count()
                worked_days.amount = version.l10n_il_computed_daily_wage * days * amount_rate
