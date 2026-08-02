from odoo import api, fields, models


class HrVersion(models.Model):
    _inherit = "hr.version"

    # --- סוג שכר ומסלולי שכר ---
    # *** הערה חשובה - אל תשנה בלי לקרוא עד הסוף ***
    # המפתח הפנימי 'hourly' הוא ערך-תאימות טכני של Odoo בלבד - הוא *לא*
    # אומר "שעתי" מבחינה עסקית. המשתמש הישראלי לעולם לא רואה/בוחר "שעתי":
    # ה-selection_add למטה מחליף את שתי התוויות הילידיות ('monthly'->'חודשי',
    # 'hourly'->'יומי') כך שבפועל יש רק שני מצבים גלויים: חודשי/יומי. הסוג
    # העסקי "יומי" ממופה תחת המפתח הטכני 'hourly' בכוונה תחילה (לא נוסף ערך
    # 'daily' חדש ונפרד) - כי מנוע השכר הילידי של Odoo (worked_days
    # fallback, contract_wage/GROSS, ערכי חופשה/חג) בודק בכמה מקומות ליבה
    # (לא ניתנים לשינוי בלי override על כמה שיטות מקור) ממש `wage_type ==
    # 'hourly'`, ומצפה ש-hourly_wage יהיה תעריף שעתי תקין. אם ניצור ערך
    # 'daily' אמיתי ונפרד, כל אותן בדיקות ליבה יפסיקו לזהות את העובד הישראלי
    # היומי ויחזרו לחישוב חודשי שגוי. לכן: תמיד תואם 1:1 "יומי בעברית" =
    # "hourly באחסון" - זו לא טעות, זו הכוונה.
    wage_type = fields.Selection(
        selection_add=[("monthly", "חודשי"), ("hourly", "יומי")],
        string="סוג שכר",
    )
    # wage הילידי נשאר בדיוק כפי שהוא (שדה שכר חודשי רגיל, לא נגענו בו) -
    # הוא שדה-המקור לעובד חודשי. לעובד יומי, wage לא רלוונטי כלל - שדה
    # נפרד (l10n_il_daily_wage) הוא שדה-המקור. אין ניסיון לסנכרן/לשקף בין
    # השניים (compute+inverse בין שני שדות-מקור נבדק ונמצא שביר: כשמשנים
    # ביחד, באותה כתיבה, גם structure_type_id (שגורר שינוי ב-wage_type דרך
    # native _compute_wage_type) וגם ערך wage בו-זמנית, סדר-העיבוד הפנימי
    # של Odoo יכול להשאיר את שני השדות לא-מסונכרנים - נצפה בפועל). במקום
    # זה: בתצוגה, מציגים את wage או את l10n_il_daily_wage לסירוגין (בדיוק
    # מקום אחד, invisible הדדי לפי wage_type) - ראו hr_employee_views.xml.
    l10n_il_daily_wage = fields.Monetary(
        string="שכר יומי", groups="hr_payroll.group_hr_payroll_user", tracking=True,
        help="מקור החישוב כאשר סוג השכר הוא יומי (ולא שעתי-אמיתי) - שכר "
             "שעתי/שבועי/חודשי נגזרים ממנו לפי לוח העבודה.",
    )
    # "יומי" (wage_type=='hourly', ברירת מחדל) - שכר יומי הוא שדה-המקור,
    # שעתי נגזר ממנו (וימי עבודה מתעגלים תמיד ליום מלא - ראו
    # hr_payslip_worked_days.py). "שעתי" - שכר שעתי הוא שדה-המקור
    # (l10n_il_true_hourly_rate, לא hourly_wage עצמו - ראו ההערה שם למה),
    # יומי/שבועי/חודשי נגזרים ממנו, והשעות *לא* מתעגלות - משולם בדיוק לפי
    # שעות בפועל (ראו hr_payslip_worked_days.py, מדלג על העיגול-ליום כשזה
    # המצב). שני המצבים תחת אותו wage_type='hourly' טכני - ראו ההערה שם.
    l10n_il_hourly_kind = fields.Selection(
        [("daily", "יומי"), ("true_hourly", "שעתי")],
        string="חישוב יומי/שעתי", default="daily",
        groups="hr_payroll.group_hr_payroll_user", tracking=True,
        help="יומי: שכר יומי הוא המקור, כל יום עבודה מתעגל לשכר יומי מלא. "
             "שעתי: שכר שעתי הוא המקור, משולם בדיוק לפי שעות בפועל - בלי "
             "עיגול ליום.",
    )
    l10n_il_true_hourly_rate = fields.Monetary(
        string="שכר לשעה (מקור)", groups="hr_payroll.group_hr_payroll_user", tracking=True,
        help="מקור החישוב כאשר סוג השכר שעתי-אמיתי (l10n_il_hourly_kind='true_hourly') - "
             "יומי/שבועי/חודשי נגזרים ממנו לפי לוח העבודה.",
    )
    l10n_il_weekend_daily_wage = fields.Monetary(
        string="שכר יום שישי/שבת", groups="hr_payroll.group_hr_payroll_user", tracking=True,
        help="שכר היום כאשר המשמרת חלה ביום שישי/שבת (מקומי) - במקום שכר יומי חול. "
             "רלוונטי רק לעובד שלוח הזמנים שלו מסוג 'משמרות' (ראו mdl_attendances). "
             "ריק = ישתמש בשכר יומי חול הרגיל.",
    )
    l10n_il_computed_daily_wage = fields.Monetary(
        string="שכר יומי (מחושב)", compute="_compute_l10n_il_wage_bases", store=True, compute_sudo=True,
        groups="hr_payroll.group_hr_payroll_user",
        help="שכר יומי לצפייה בלבד כאשר סוג השכר חודשי - נגזר מהשכר החודשי לפי לוח העבודה.",
    )
    l10n_il_computed_weekly_wage = fields.Monetary(
        string="שכר שבועי", compute="_compute_l10n_il_wage_bases", store=True, compute_sudo=True,
        groups="hr_payroll.group_hr_payroll_user")
    l10n_il_computed_monthly_wage = fields.Monetary(
        string="שכר חודשי (מחושב)", compute="_compute_l10n_il_wage_bases", store=True, compute_sudo=True,
        groups="hr_payroll.group_hr_payroll_user",
        help="שכר חודשי לצפייה בלבד כאשר סוג השכר יומי - נגזר מהשכר היומי לפי לוח העבודה.",
    )
    l10n_il_extra_day_rate = fields.Monetary(
        string="תעריף יום נוסף", default=0.0, groups="hr_payroll.group_hr_payroll_user", tracking=True,
        help="תעריף ליום נוסף (0 = העובד אינו מקבל תשלום עבור יום נוסף). רלוונטי לעובד חודשי בלבד.",
    )

    # --- שעות נוספות ---
    l10n_il_overtime_payment_type = fields.Selection(
        [("percentage", "אחוז משווי שעה"), ("fixed", "סכום קבוע לשעה")],
        string="שיטת תשלום לשעה נוספת", groups="hr_payroll.group_hr_payroll_user", tracking=True,
    )
    l10n_il_overtime_percentage = fields.Float(
        string="אחוז משווי שעה", groups="hr_payroll.group_hr_payroll_user", tracking=True,
        help="לדוגמה 150 = פי 1.5 משווי השעה הרגילה.",
    )
    l10n_il_overtime_fixed_rate = fields.Monetary(
        string="סכום קבוע לשעה נוספת", groups="hr_payroll.group_hr_payroll_user", tracking=True)
    l10n_il_computed_overtime_hour_rate = fields.Monetary(
        string="תעריף שעה נוספת מחושב", compute="_compute_l10n_il_overtime_hour_rate",
        groups="hr_payroll.group_hr_payroll_user",
        help="התעריף שישולם בפועל עבור שעה נוספת אחת - לפי אחוז משווי השעה או סכום קבוע, לפי הבחירה.",
    )

    # hourly_wage (השדה הילידי) הוא זה שמנוע ה-BASIC הילידי
    # (hr_payslip_worked_days._compute_amount) קורא בפועל כש-wage_type=='hourly'
    # (=יומי עסקית, ראו ההערה למעלה) - חובה שיהיה מחושב אוטומטית ולעולם לא
    # ניתן להזנה ידנית: המשתמש קובע רק שכר יומי/חודשי, ושכר שעתי תמיד נגזר
    # מזה + לוח העבודה. מוצג לצפייה תמיד (בשני סוגי השכר), ולכן הפך כאן
    # לשדה מחושב-בלבד, readonly תמיד, בלי קשר לסוג השכר הנוכחי.
    hourly_wage = fields.Monetary(
        string="שכר שעתי", compute="_compute_l10n_il_wage_bases", store=True, compute_sudo=True, readonly=True,
        groups="hr_payroll.group_hr_payroll_user", tracking=True,
    )

    def _l10n_il_calendar_profile(self):
        """(ימי עבודה בשבוע, שעות ביום) לפי לוח העבודה - ימי עבודה = מספר
        ה-dayofweek הייחודיים עם שורת נוכחות בלוח; שעות ביום = השדה הילידי
        hours_per_day של הלוח עצמו (לא סכימה עצמאית מ-hours_per_week/ימים -
        על לוח משמרות (mdl_attendances) hours_per_week סוכם גם בוקר וגם ערב
        על אותו יום, מה שהיה נותן כאן תוצאה כפולה; hours_per_day הוא השדה
        שכל לוח - כולל לוח משמרות, שדורס את חישובו - מבטיח שמשקף את מה
        שבאמת נחשב "יום עבודה" בלוח הזה). משמש כבסיס להמרה בין שכר
        יומי/שעתי/שבועי/חודשי - לא לחישוב שכר תלוש בפועל (זה ממשיך להתבסס על
        worked_days_line_ids האמיתיים של כל תלוש, ראו hr_payslip_worked_days.py)."""
        self.ensure_one()
        calendar = self.resource_calendar_id
        work_days = len(set(calendar.attendance_ids.mapped("dayofweek"))) or 5
        hours_per_day = calendar.hours_per_day or ((calendar.hours_per_week or (work_days * 8.0)) / work_days if work_days else 0.0)
        return work_days, hours_per_day

    @api.depends(
        "wage_type", "wage", "l10n_il_daily_wage", "l10n_il_hourly_kind", "l10n_il_true_hourly_rate",
        "resource_calendar_id.attendance_ids.dayofweek",
        "resource_calendar_id.hours_per_day", "resource_calendar_id.hours_per_week",
    )
    def _compute_l10n_il_wage_bases(self):
        for version in self:
            work_days_per_week, hours_per_day = version._l10n_il_calendar_profile()
            avg_days_per_month = work_days_per_week * 52 / 12
            if version.wage_type == "hourly" and version.l10n_il_hourly_kind == "true_hourly":
                # שעתי-אמיתי: שכר לשעה הוא שדה-המקור (לא נגזר) - יומי/חודשי
                # נגזרים ממנו, לא ההפך.
                hourly = version.l10n_il_true_hourly_rate
                daily = hourly * hours_per_day
                monthly = daily * avg_days_per_month
            elif version.wage_type == "hourly":  # "יומי" עסקית, ראו הערת wage_type למעלה
                daily = version.l10n_il_daily_wage
                monthly = daily * avg_days_per_month
                hourly = (daily / hours_per_day) if hours_per_day else 0.0
            else:
                monthly = version.wage
                daily = (monthly / avg_days_per_month) if avg_days_per_month else 0.0
                hourly = (daily / hours_per_day) if hours_per_day else 0.0
            version.l10n_il_computed_daily_wage = daily
            version.l10n_il_computed_monthly_wage = monthly
            version.l10n_il_computed_weekly_wage = daily * work_days_per_week
            version.hourly_wage = hourly

    @api.depends("l10n_il_overtime_payment_type", "l10n_il_overtime_percentage", "l10n_il_overtime_fixed_rate", "hourly_wage")
    def _compute_l10n_il_overtime_hour_rate(self):
        for version in self:
            if version.l10n_il_overtime_payment_type == "fixed":
                version.l10n_il_computed_overtime_hour_rate = version.l10n_il_overtime_fixed_rate
            else:
                version.l10n_il_computed_overtime_hour_rate = version.hourly_wage * version.l10n_il_overtime_percentage / 100.0

    # --- העסקה ---
    l10n_il_employee_category = fields.Selection(
        selection=[
            ("israeli", "עובד ישראלי"),
            ("foreign", "עובד זר"),
            ("palestinian", "עובד פלסטיני"),
        ],
        string="קטגוריית עובד",
        default="israeli",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="הקטגוריה הסטטוטורית של העובד. קובעת אילו כללי שכר, דיווחים וניכויים חלים עליו.",
    )
    # --- מס הכנסה ---
    l10n_il_tax_residency = fields.Selection(
        selection=[
            ("resident", "תושב ישראל"),
            ("non_resident", "תושב חוץ"),
        ],
        string="תושבות לצורכי מס",
        default="resident",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_credit_points = fields.Float(
        string="נקודות זיכוי",
        default=2.25,
        digits=(16, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="מספר נקודות הזיכוי של העובד לפי טופס 101. שווי הנקודה נקבע בפרמטר שנתי.",
    )
    l10n_il_main_employer = fields.Boolean(
        string="מעסיק עיקרי",
        default=True,
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="כאשר לא מסומן (מעסיק משני), ללא אישור תיאום מס ינוכה מס מרבי.",
    )
    l10n_il_tax_coordination = fields.Boolean(
        string="תיאום מס",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="מסומן כאשר קיים אישור תיאום מס בתוקף מרשות המסים.",
    )
    l10n_il_tax_coordination_rate = fields.Float(
        string="שיעור מס לפי תיאום (%)",
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור המס הקבוע מהאישור. כאשר מוגדר, המס מחושב לפי שיעור זה במקום מדרגות המס.",
    )
    l10n_il_tax_coordination_expiry = fields.Date(
        string="תוקף אישור תיאום מס",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_settlement_code = fields.Char(
        string="קוד יישוב מזכה",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="קוד היישוב לצורך הטבת מס ביישוב מוטב, כאשר העובד זכאי.",
    )

    # --- פנסיה ופיצויים ---
    l10n_il_pension_fund_id = fields.Many2one(
        "res.partner",
        string="קרן פנסיה",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="הגוף המוסדי המנהל את ההסדר הפנסיוני של העובד.",
    )
    l10n_il_pension_member_no = fields.Char(
        string="מספר עמית בקרן",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_pension_employee_rate = fields.Float(
        string="פנסיה - עובד (%)",
        default=6.0,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור ניכוי העובד לתגמולים. המינימום לפי צו ההרחבה: 6%.",
    )
    l10n_il_pension_employer_rate = fields.Float(
        string="פנסיה - מעסיק (%)",
        default=6.5,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור הפרשת המעסיק לתגמולים. המינימום לפי צו ההרחבה: 6.5%.",
    )
    l10n_il_severance_rate = fields.Float(
        string="פיצויים - מעסיק (%)",
        default=6.0,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="שיעור הפרשת המעסיק לפיצויים. המינימום לפי צו ההרחבה: 6%; הפרשה מלאה לפי סעיף 14: 8.33%.",
    )
    l10n_il_section14 = fields.Boolean(
        string="סעיף 14",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
        help="מסומן כאשר חל על העובד האישור הכללי לפי סעיף 14 לחוק פיצויי פיטורים.",
    )

    # --- פרטים אישיים לטופס 101 ---
    l10n_il_aliyah_date = fields.Date(
        string="תאריך עלייה",
        groups="hr.group_hr_user",
        tracking=True,
    )
    l10n_il_spouse_id = fields.Char(
        string="מספר זהות של בן/בת הזוג",
        groups="hr.group_hr_user",
        tracking=True,
    )
    l10n_il_kupat_holim = fields.Selection(
        selection=[
            ("clalit", "כללית"),
            ("maccabi", "מכבי"),
            ("meuhedet", "מאוחדת"),
            ("leumit", "לאומית"),
        ],
        string="קופת חולים",
        groups="hr.group_hr_user",
        tracking=True,
    )

    # --- קרן השתלמות ---
    l10n_il_hishtalmut = fields.Boolean(
        string="קרן השתלמות",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_hishtalmut_fund_id = fields.Many2one(
        "res.partner",
        string="קרן השתלמות - גוף מנהל",
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_hishtalmut_employee_rate = fields.Float(
        string="קרן השתלמות - עובד (%)",
        default=2.5,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
    l10n_il_hishtalmut_employer_rate = fields.Float(
        string="קרן השתלמות - מעסיק (%)",
        default=7.5,
        digits=(5, 2),
        groups="hr_payroll.group_hr_payroll_user",
        tracking=True,
    )
