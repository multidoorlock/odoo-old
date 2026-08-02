from odoo import api, fields, models
from odoo.tools import float_is_zero

DAYS_PER_YEAR = 365.25


class HrPayslip(models.Model):
    """נוסחאות הניכויים הסטטוטוריים (מס הכנסה, ביטוח לאומי, בריאות) כפונקציות
    טהורות של סכום ברוטו היפותטי - מקור אמת יחיד: גם כללי השכר האמיתיים
    (IL_INCTAX/IL_NII_EE/IL_HEALTH_EE, ראו hr_salary_rule_data.xml) וגם פותר
    הגילום (gross-up, ראו _l10n_il_gross_up למטה - נצרך ע"י l10n_il_hr_payroll_account
    עבור התאמות שכר עם סוג השפעה='נטו') קוראים לאותן הפונקציות, כדי שלא יהיה
    סיכוי שהם יסטו זה מזה עם הזמן.
    """
    _inherit = "hr.payslip"

    # שני שדות Many2many מחושבים (לא stored, וירטואליים לגמרי) - תת-קבוצה
    # מסוננת של line_ids, לשימוש בטאבים "חישוב שכר"/"עלות מעסיק". לא נשען על
    # domain= בתצוגה על שדה line_ids עצמו - domain על שדה x2many שכבר "קיים"
    # (לא בשימוש לבחירה/יצירה) לא בהכרח מסנן את מה שמוצג בפועל בווידג'ט הרשימה
    # (נצפה ישירות: שתי הטאבים הראו את כל השורות ללא הבדל, למרות domain בתצוגה) -
    # שדה מחושב נפרד מבטיח סינון נכון בלי תלות בהתנהגות ה-widget.
    l10n_il_salary_computation_line_ids = fields.Many2many(
        "hr.payslip.line", compute="_compute_l10n_il_split_lines", string="חישוב שכר")
    l10n_il_employer_cost_line_ids = fields.Many2many(
        "hr.payslip.line", compute="_compute_l10n_il_split_lines", string="עלות מעסיק")

    @api.depends("line_ids", "line_ids.category_id", "line_ids.code")
    def _compute_l10n_il_split_lines(self):
        for slip in self:
            slip.l10n_il_employer_cost_line_ids = slip.line_ids.filtered(
                lambda l: l.code == "GROSS" or l.category_id.code == "IL_EMPLOYER")
            # NET_TO_PAY מוצג בנפרד כסה"כ מודגש מתחת לטבלה (כמו employer_cost
            # בטאב עלות מעסיק) - לא כשורה בתוך הטבלה עצמה, ראו hr_payslip_views.xml.
            slip.l10n_il_salary_computation_line_ids = slip.line_ids.filtered(
                lambda l: l.category_id.code != "IL_EMPLOYER" and l.code != "NET_TO_PAY")

    def _l10n_il_basic_pension_tax_credit(self, basic):
        """זיכוי המס מהפרשת הפנסיה - תלוי ב-BASIC (לא ב-GROSS), ולכן קבוע
        ואינו משתנה כשמוסיפים ל-GROSS (למשל דרך גילום/gross-up). basic מתקבל
        כפרמטר ולא נקרא מ-self.line_ids - בזמן שהכלל עצמו רץ (בתוך אותה
        קריאת compute_sheet), line_ids עדיין ריק (השורות נוצרות רק בסוף כל
        הפאס, ראו compute_sheet הילידי) - הערך החי היחיד הוא categories['BASIC']."""
        self.ensure_one()
        version = self.version_id
        pens_rate = version.l10n_il_pension_employee_rate
        if not pens_rate:
            pens_rate = self._rule_parameter("l10n_il_pension_min_rates")["employee"] * 100
        credit_rate = self._rule_parameter("l10n_il_pension_tax_credit_rate")
        return basic * pens_rate / 100.0 * credit_rate

    def _l10n_il_income_tax_for_gross(self, gross, basic_pension_tax_credit=0.0):
        self.ensure_one()
        version = self.version_id
        if version.l10n_il_tax_coordination and version.l10n_il_tax_coordination_rate:
            return gross * version.l10n_il_tax_coordination_rate / 100.0
        if not version.l10n_il_main_employer:
            return gross * 0.47
        brackets = self._rule_parameter("l10n_il_tax_brackets")
        tax = 0.0
        for low, high, rate in brackets:
            if gross > low:
                top = min(gross, high) if high else gross
                tax += (top - low) * rate
        point_value = self._rule_parameter("l10n_il_credit_point_value")
        credit = version.l10n_il_credit_points * point_value + basic_pension_tax_credit
        return max(tax - credit, 0.0)

    def _l10n_il_nii_rate_parameter_code(self):
        """קוד פרמטר שיעורי הביטוח הלאומי/בריאות הרלוונטי לפי קטגוריית העובד
        הסטטוטורית (l10n_il_employee_category, ראו hr_version.py) - "ישראלי"
        משתמש בטבלת תושב ישראל הרגילה (ברירת המחדל, ללא שינוי התנהגות); "פלסטיני"
        (תושב יהודה/שומרון/עזה) ו"זר" (תושב חוץ) משתמשים בטבלאות המופחתות
        הנפרדות שלהם לפי לוחות ביטוח לאומי הרשמיים - שתיהן ללא ביטוח בריאות כלל
        (ראו rule_parameter_il_nii_rates_west_bank/_foreign, מקור: btl.gov.il)."""
        self.ensure_one()
        category = self.version_id.l10n_il_employee_category
        if category == "palestinian":
            return "l10n_il_nii_rates_west_bank"
        if category == "foreign":
            return "l10n_il_nii_rates_foreign"
        return "l10n_il_nii_rates"

    def _l10n_il_nii_ee_for_gross(self, gross):
        self.ensure_one()
        p = self._rule_parameter(self._l10n_il_nii_rate_parameter_code())
        base = min(gross, p["max_ceiling"])
        reduced = min(base, p["reduced_ceiling"])
        full = max(base - p["reduced_ceiling"], 0.0)
        return reduced * p["employee_nii_reduced"] + full * p["employee_nii_full"]

    def _l10n_il_nii_er_for_gross(self, gross):
        self.ensure_one()
        p = self._rule_parameter(self._l10n_il_nii_rate_parameter_code())
        base = min(gross, p["max_ceiling"])
        reduced = min(base, p["reduced_ceiling"])
        full = max(base - p["reduced_ceiling"], 0.0)
        return reduced * p["employer_reduced"] + full * p["employer_full"]

    def _l10n_il_health_ee_for_gross(self, gross):
        self.ensure_one()
        p = self._rule_parameter(self._l10n_il_nii_rate_parameter_code())
        base = min(gross, p["max_ceiling"])
        reduced = min(base, p["reduced_ceiling"])
        full = max(base - p["reduced_ceiling"], 0.0)
        return reduced * p["employee_health_reduced"] + full * p["employee_health_full"]

    def _l10n_il_seniority_years(self):
        """ותק (שנות עבודה מושלמות, כשבר עשרוני) נכון לסוף תקופת התלוש - לפי
        תאריך תחילת ההעסקה הראשון (הילידי, ללא פערים)."""
        self.ensure_one()
        start = self.employee_id._get_first_contract_date()
        if not start or not self.date_to:
            return 0.0
        return max((self.date_to - start).days, 0) / DAYS_PER_YEAR

    def _l10n_il_travel_exempt_ceiling(self):
        """תקרת הפטור ממס/ביטוח לאומי/בריאות להחזר נסיעות: התעריף היומי
        הסטטוטורי (l10n_il_travel_daily_cap) כפול ימי העבודה בפועל בתקופת
        התלוש (worked_days_line_ids ששולמו) - מעבר לתקרה, ההחזר חייב במס כרגיל."""
        self.ensure_one()
        daily_cap = self._rule_parameter("l10n_il_travel_daily_cap")
        worked_days = sum(self.worked_days_line_ids.filtered("is_paid").mapped("number_of_days"))
        return daily_cap * worked_days

    def _l10n_il_havraa_exempt_ceiling(self):
        """תקרת הפטור לדמי הבראה: ערך יום הבראה (l10n_il_havraa_day_value)
        כפול מספר ימי הזכאות לפי ותק (l10n_il_havraa_eligible_days)."""
        self.ensure_one()
        day_value = self._rule_parameter("l10n_il_havraa_day_value")
        years = self._l10n_il_seniority_years()
        tiers = self._rule_parameter("l10n_il_havraa_eligible_days")
        eligible_days = 0
        for low, high, tier_days in tiers:
            if years >= low and (high is None or years < high):
                eligible_days = tier_days
                break
        return day_value * eligible_days

    def _l10n_il_tax_exempt_income(self):
        """סה"כ הכנסה פטורה ממס הכנסה/ביטוח לאומי/בריאות מתוך הכנסות התלוש -
        החזר נסיעות ודמי הבראה, פטורים עד התקרה הסטטוטורית (מעל זה - חייב
        במס כרגיל, ראו _l10n_il_travel_exempt_ceiling/_l10n_il_havraa_exempt_ceiling).
        לא משנה את ה-GROSS המדווח עצמו (הסכום המלא עדיין נכנס לברוטו) - רק
        את בסיס החישוב למס/ביטוח לאומי/בריאות (ראו IL_INCTAX/IL_NII_EE/IL_HEALTH_EE).
        חל על ההכנסה ללא קשר למקור שלה (Salary Input ידני או התאמת שכר).
        """
        self.ensure_one()
        # כולל גם את הקודים "..._GROSS"/"..._NET" (ראו l10n_il_hr_payroll_account,
        # מזרים אליהם התאמות שכר) - התקרה משותפת לסכום הכולל של הסוג הזה, לא משנה
        # אם הוזן כ-Salary Input ידני או דרך התאמת שכר, ברוטו או נטו.
        travel_amount = sum(self.input_line_ids.filtered(
            lambda i: i.input_type_id.code in ("IL_TRAVEL", "IL_TRAVEL_GROSS", "IL_TRAVEL_NET")).mapped("amount"))
        havraa_amount = sum(self.input_line_ids.filtered(
            lambda i: i.input_type_id.code in ("IL_HAVRAA", "IL_HAVRAA_GROSS", "IL_HAVRAA_NET")).mapped("amount"))
        travel_exempt = min(travel_amount, self._l10n_il_travel_exempt_ceiling()) if travel_amount > 0 else 0.0
        havraa_exempt = min(havraa_amount, self._l10n_il_havraa_exempt_ceiling()) if havraa_amount > 0 else 0.0
        return travel_exempt + havraa_exempt

    def _l10n_il_pension_eligible_extra(self):
        """תוספת לבסיס הפרשת הפנסיה (חלק עובד/מעסיק) מעבר ל-BASIC - ברירת מחדל 0
        (אין תוספת, ההתנהגות המקורית: פנסיה תמיד רק מ-BASIC). מורחב ב-
        l10n_il_hr_payroll_account (ראו L10N_IL_PENSION_ELIGIBLE_TYPES) עבור סוגי
        התאמת שכר שסומנו במפורש כמשפיעים גם על הפרשת הפנסיה (לא רק על
        מס הכנסה/ביטוח לאומי/בריאות) - למשל עמלה/תוספת אחרת."""
        self.ensure_one()
        return 0.0

    def _l10n_il_total_ee_deduction_for_gross(self, gross, basic_pension_tax_credit=0.0, pension_rate=0.0):
        """סה"כ ניכוי חובה (מס הכנסה + ביטוח לאומי + בריאות, חלק עובד) כפונקציה
        של ברוטו היפותטי. פנסיה/השתלמות עובד תלויים ב-BASIC בדרך כלל (לא ב-GROSS)
        ולכן אינם מושפעים מגילום שנכנס דרך ALW - אלא אם pension_rate>0 (הסוג
        הספציפי שמתגלם מסומן כמשפיע גם על בסיס הפנסיה, ראו _l10n_il_pension_eligible_extra) -
        או-אז מתווסף ניכוי פנסיה פרופורציונלי לברוטו ההיפותטי גם כאן, באותו
        אופן דיפרנציאלי (הפרש בין baseline ל-new) כמו שאר המיסים."""
        return (
            self._l10n_il_income_tax_for_gross(gross, basic_pension_tax_credit)
            + self._l10n_il_nii_ee_for_gross(gross)
            + self._l10n_il_health_ee_for_gross(gross)
            + gross * pension_rate / 100.0
        )

    def _l10n_il_gross_up(self, target_net_delta, baseline_taxable_gross, basic, remaining_exemption=0.0, pension_rate=0.0):
        """פותר בביסקציה: איזו תוספת לברוטו (ΔG, יכולה להיות שלילית) גורמת
        לנטו לעלות/לרדת בדיוק ב-target_net_delta, החל מ-baseline_taxable_gross
        (הבסיס החייב-במס לפני הגילום - כבר אחרי הפחתת כל הכנסה פטורה קיימת,
        ראו _l10n_il_tax_exempt_income). מדויק גם כשהיעד חוצה מדרגת מס/תקרת
        ביטוח לאומי, כי פותר על הנוסחה האמיתית (לא קירוב לפי שיעור שולי בודד).
        basic מתקבל כפרמטר (ה-BASIC בפועל - כבר מחושב וקיים ב-line_ids בשלב
        הזה, אחרי compute_sheet הראשון, בניגוד לכללים עצמם שרצים תוך כדי).

        remaining_exemption: יתרת תקרת פטור (נסיעות/הבראה) שעוד לא נוצלה על
        ידי הכנסה פטורה אחרת מאותו סוג באותו תלוש - חלק מ-ΔG עד לגובה הזה
        נכנס 1:1 לנטו (בלי מס בכלל), רק העודף מעבר לזה עובר גילום מס מלא.
        ברירת מחדל 0 (ללא פטור כלל) - ההתנהגות המקורית, ללא שינוי לסוגים
        שאין להם תקרת פטור (עמלה/תוספת אחרת).

        pension_rate: קצב הפרשת פנסיה-חלק-עובד (אחוזים) שחל גם על ה-ΔG הזה
        (מעבר למס הכנסה/ביטוח לאומי/בריאות) - רק לסוגים שסומנו כך (ראו
        _l10n_il_pension_eligible_extra/L10N_IL_PENSION_ELIGIBLE_TYPES). ברירת
        מחדל 0 (ללא השפעה על פנסיה, ההתנהגות המקורית).
        """
        self.ensure_one()
        if float_is_zero(target_net_delta, precision_digits=2):
            return 0.0
        basic_credit = self._l10n_il_basic_pension_tax_credit(basic)
        baseline_ded = self._l10n_il_total_ee_deduction_for_gross(baseline_taxable_gross, basic_credit, pension_rate)

        def net_delta(delta_gross):
            if delta_gross >= 0:
                exempt_part = min(delta_gross, remaining_exemption)
            else:
                exempt_part = max(delta_gross, -remaining_exemption)
            taxable_part = delta_gross - exempt_part
            new_taxable_gross = max(baseline_taxable_gross + taxable_part, 0.0)
            new_ded = self._l10n_il_total_ee_deduction_for_gross(new_taxable_gross, basic_credit, pension_rate)
            return delta_gross - (new_ded - baseline_ded)

        # net_delta מונוטונית עולה ב-delta_gross (השיעור השולי בין 0% ל-100%,
        # לעולם לא שלילי) ו-net_delta(0)==0 - ולכן |delta_gross| הדרוש תמיד
        # לפחות |target_net_delta|, גבול בטוח להתחיל ממנו ולהכפיל עד שמספיק.
        if target_net_delta > 0:
            lo, hi = 0.0, target_net_delta
            while net_delta(hi) < target_net_delta:
                hi *= 2
        else:
            lo, hi = target_net_delta, 0.0
            while net_delta(lo) > target_net_delta:
                lo *= 2
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if net_delta(mid) < target_net_delta:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0
