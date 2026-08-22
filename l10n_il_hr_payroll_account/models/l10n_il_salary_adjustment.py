from odoo import api, fields, models
from odoo.tools import float_is_zero

# כל 7 הסוגים הזמינים כ"התאמת שכר" (available_in_attachments=True, מוגדרים
# ב-l10n_il_hr_payroll) - כולם מקבלים בדיוק את אותו מנגנון ברוטו/נטו +
# חיובי/שלילי, ללא הבדל בין סוג "תוספת" (עמלה/נסיעות/הבראה/תוספת אחרת) לסוג
# "ניכוי" (הלוואה/ארוחות/ניכוי אחר) - הניתוב נקבע אך ורק ע"י l10n_il_impact_type
# וסימן הסכום, לא ע"י הקטגוריה המקורית של הסוג. הערך (value) הוא שם ה-xmlid
# suffix המשותף לזוג ה-inputs הייעודיים של אותו סוג (input_il_{key}_gross/_net).
L10N_IL_SALARY_ADJUSTMENT_TYPES = {
    "IL_COMMISSION": "commission",
    "IL_TRAVEL": "travel",
    "IL_HAVRAA": "havraa",
    "IL_OTHER_ADD": "other_add",
    "IL_LOAN_GIVEN": "loan_given",
    "IL_LOAN": "loan",
    "IL_MEALS": "meals",
    "IL_OTHER_DED": "other_ded",
}

# סימן מותר לכל סוג (חיובי בלבד/שלילי בלבד, לא השני ולא 0) - נאכף ב-
# hr.salary.attachment._check_amount_sign למטה, ובכל מסך/אשף שיוצר סכום
# (ראו l10n_il_payment_batch.py, l10n_il_salary_adjustment_payment_wizard.py).
L10N_IL_POSITIVE_ONLY_TYPES = {"IL_COMMISSION", "IL_TRAVEL", "IL_HAVRAA", "IL_OTHER_ADD", "IL_LOAN_GIVEN"}
L10N_IL_NEGATIVE_ONLY_TYPES = {"IL_LOAN", "IL_MEALS", "IL_OTHER_DED"}

# סוגים עם תקרת פטור ממס/ביטוח לאומי/בריאות (נסיעות/הבראה) - שם המתודה ב-
# hr.payslip (l10n_il_hr_payroll) שמחשבת את התקרה. הסכום עדיין נכנס ל-GROSS
# (קטגוריית ALW) - הפטור מתבצע ע"י הפחתת בסיס המס (ראו hr.payslip.
# _l10n_il_tax_exempt_income ב-l10n_il_hr_payroll), לא ע"י ניתוב קטגוריה.
L10N_IL_EXEMPT_CEILING_METHODS = {
    "IL_TRAVEL": "_l10n_il_travel_exempt_ceiling",
    "IL_HAVRAA": "_l10n_il_havraa_exempt_ceiling",
}

# סוגים פטורים לגמרי (מס הכנסה/ביטוח לאומי/בריאות) בלי תקרה כלל - הסכום לעולם
# לא נכנס ל-GROSS/ALW (גם בצד "ברוטו" ישיר וגם בצד "נטו" מגולם), אלא ישירות
# לקטגוריית ניכויי-רשות (rule_category_il_other_ded, ראה hr_salary_rule_data.xml
# - ילדה של DED, לא נטענת ב-GROSS כלל) - הסכום פשוט זז נטו 1:1, בלי שום חישוב
# מס. לכן ל"נטו" מסוג כזה תמיד remaining_exemption=inf (הגילום פותר יחס 1:1).
L10N_IL_UNTAXED_TYPES = {"IL_LOAN_GIVEN", "IL_LOAN", "IL_MEALS", "IL_OTHER_DED"}

# סוגים שחלה עליהם גם הפרשת פנסיה (לא רק מס הכנסה/ביטוח לאומי/בריאות) - הסכום
# (גם ברוטו-ישיר וגם נטו-מגולם) מגדיל את בסיס הפרשת הפנסיה (עובד+מעסיק) מעבר
# ל-BASIC בלבד. ראה HrPayslip._l10n_il_pension_eligible_extra למטה ו-
# hr.payslip._l10n_il_pension_eligible_extra/_l10n_il_total_ee_deduction_for_gross
# ב-l10n_il_hr_payroll. שאר הסוגים (כולל נסיעות/הבראה שכבר פטורים ממס) אינם
# משפיעים על הפנסיה כלל - ההתנהגות המקורית (פנסיה רק מ-BASIC).
L10N_IL_PENSION_ELIGIBLE_TYPES = {"IL_COMMISSION", "IL_OTHER_ADD"}


class HrSalaryAttachment(models.Model):
    """התאמת שכר (Salary Adjustment): מרחיב את התכונה הקיימת של אודו בשדה
    "סוג השפעה" - חל על כל סוגי ההתאמה (גם "תוספת" וגם "ניכוי" כאחד), קובע
    איך הסכום משפיע על השכר, ביחד עם הסימן (חיובי/שלילי) שלו:

    ברוטו + חיובי: נכנס *לפני* שכר ברוטו (כמו תוספת רגילה) - מעלה את הברוטו
    המדווח, ממוסה כרגיל (עם הטיפול-מס הספציפי של הסוג, אם יש - למשל פטור
    לנסיעות/הבראה, ראו hr.payslip._l10n_il_tax_exempt_income ב-l10n_il_hr_payroll).

    ברוטו + שלילי: נכנס *בין* ברוטו לנטו - מקטין רק את הנטו, בלי מס, ובלי
    לגעת בברוטו המדווח (למשל קיזוז/החזרה - לא רטרואקטיבי על מה שהעובד "הרוויח"
    בפועל באותה תקופה).

    נטו (כל סימן): הסכום שהוזן הוא היעד לשינוי בנטו (NET) עצמו. המערכת פותרת
    בביסקציה (גילום/gross-up, ראו HrPayslip._l10n_il_apply_net_impact_gross_up
    למטה ו-hr.payslip._l10n_il_gross_up ב-l10n_il_hr_payroll) איזו תוספת
    ברוטו-שקולה נדרשת כדי שהנטו יגיע בדיוק לסכום שהוזן - ממשיך לזוז את ה-NET
    עצמו (לא רק את "נטו לתשלום").

    אין קשר בין התאמת שכר לתשלום (account.payment) - זו רשומה עצמאית לגמרי.
    ניתן עדיין לשייך אותה למחזור תשלומים (l10n_il_batch_id) כשנוצרה דרכו,
    למידע/סינון בלבד.
    """
    _inherit = "hr.salary.attachment"

    # מצמצם את הבחירה ל-7 הסוגים הישראלים הנתמכים בפועל (ראו
    # L10N_IL_SALARY_ADJUSTMENT_TYPES) - הבסיס הילידי (hr_payroll) כבר מגדיר
    # את השדה עם domain=[('available_in_attachments','=',True)] בלבד, שכולל
    # גם סוגי דמו ילידיים גנריים (ATTACH_SALARY/ASSIG_SALARY/CHILD_SUPPORT)
    # שאין להם שום כלל שכר ישראלי מאחוריהם - התאמת שכר מסוג כזה נראית תקינה
    # (state='open', סכום מוגדר) אבל לא נכנסת לחישוב השכר בכלל (באג אמיתי
    # שנתפס: משתמש בחר סוג דמו כזה, ההתאמה לא הופיעה בשום מקום בתלוש).
    other_input_type_id = fields.Many2one(
        domain=[("available_in_attachments", "=", True), ("code", "in", list(L10N_IL_SALARY_ADJUSTMENT_TYPES))],
    )
    l10n_il_impact_type = fields.Selection(
        [("gross", "ברוטו"), ("net", "נטו")],
        string="סוג השפעה", default="gross", required=True, tracking=True,
        help="קובע איך הסכום משפיע על השכר - חל על כל סוגי ההתאמה (גם תוספת וגם "
             "ניכוי). ברוטו חיובי: נכנס לפני שכר ברוטו, ממוסה כרגיל. ברוטו שלילי: "
             "מנוכה ישירות מהנטו בלבד, בלי מס, בלי לשנות את הברוטו המדווח. נטו: "
             "הסכום הוא היעד לשינוי בנטו עצמו (כל סימן) - המערכת פותרת (גילום) "
             "איזו תוספת ברוטו-שקולה נדרשת.",
    )
    l10n_il_batch_id = fields.Many2one(
        "l10n.il.payment.batch", string="מחזור", index=True, ondelete="set null",
        help="ריק בהתאמה בודדת (off-cycle). מידע/סינון בלבד - אין קשר תפעולי לתשלום כלשהו.",
    )
    # הסימן נקבע אך ורק לפי הסוג (ראו L10N_IL_POSITIVE_ONLY_TYPES/L10N_IL_NEGATIVE_ONLY_TYPES
    # למעלה) - לא בחירה חופשית של המשתמש (הילידי מאפשר עריכה ישירה של is_refund,
    # מה שהיה מאפשר "ערך שלישי" לא-חוקי, למשל עמלה שלילית). הופך readonly+מחושב
    # כדי שלא תהיה שום דרך (טופס בודד/אשפים) להזין שילוב לא-חוקי.
    is_refund = fields.Boolean(compute="_compute_l10n_il_is_refund", store=True, readonly=True)

    @api.depends("other_input_type_id")
    def _compute_l10n_il_is_refund(self):
        for attachment in self:
            attachment.is_refund = attachment.other_input_type_id.code in L10N_IL_NEGATIVE_ONLY_TYPES


class HrPayslip(models.Model):
    """Override מלא (לא הרחבה) של _compute_input_line_ids הילידי: התאמות שכר
    (hr.salary.attachment) לעולם לא נכתבות תחת הסוג ה"רגיל"/הידני שלהן (למשל
    "עמלה", IL_COMMISSION שב-l10n_il_hr_payroll) - זה נשאר שמור בלעדית ל-Salary
    Input שהוזן ידנית ישירות על התלוש, לא דרך התאמת שכר. במקום זה, כל התאמת
    שכר (מכל אחד מ-7 הסוגים הזמינים, ראו L10N_IL_SALARY_ADJUSTMENT_TYPES)
    מנותבת לאחד משני inputs ייעודיים פנימיים של אותו סוג (input_il_{type}_gross/
    _net) - ה"ברוטו" נכתב כאן ישירות (סעיף למטה), ה"נטו" נפתר בנפרד ב-compute_sheet
    (ראו _l10n_il_apply_net_impact_gross_up) אחרי שברוטו/בייסיק כבר ידועים.
    """
    _inherit = "hr.payslip"

    # עוקב אחרי אילו התאמות שכר (ברוטו-ישיר או נטו-מגולם, שני הצדדים יחד)
    # כבר נכללו בחישוב התלוש הזה - נבנה/מתעדכן מחדש בחופשיות כל עוד התלוש
    # מעולם לא אושר (done_date ריק, ראו is_recompute_after_confirm למטה),
    # ומ-ההגישה בלבד מאותה נקודה ואילך - כדי ש"עדכון וחישוב מחדש" (unpaid,
    # ראו account_payment.py) לא ישנה סכום שכבר "ננעל" בתלוש הזה, רק יוסיף
    # התאמות פתוחות שעדיין לא נכללו בכלל (גם אם מאותו סוג בדיוק).
    l10n_il_consumed_attachment_ids = fields.Many2many(
        "hr.salary.attachment", "hr_payslip_l10n_il_consumed_attachment_rel",
        string="התאמות שכר שכבר חושבו בתלוש זה",
    )

    def _l10n_il_close_paid_one_time_adjustments(self):
        """התאמות שכר חד-פעמיות (duration_type='one') ששייכות לתלוש הזה
        (לפי אותה בדיקת התאמה בתאריכים/סוג כמו _compute_input_line_ids) נסגרות
        אוטומטית ברגע שהתלוש מסומן כשולם - חד-פעמי פירושו שהיא שייכת בדיוק
        לתלוש אחד ולא אמורה להישאר "פתוחה" (ולהיכלל שוב, בטעות, בתלוש עתידי
        אם התלוש הזה יימחק/ייווצר מחדש על אותה תקופה)."""
        adjustment_types = self._l10n_il_salary_adjustment_input_types()
        if not adjustment_types:
            return
        for slip in self:
            if not slip.employee_id or not slip.date_to:
                continue
            valid_one_time = slip.employee_id.salary_attachment_ids.filtered(
                lambda a: a.state == "open" and a.duration_type == "one"
                    and a.other_input_type_id.code in adjustment_types
                    and a.date_start <= slip.date_to
                    and (not a.date_end or a.date_end >= slip.date_from)
            )
            valid_one_time.action_close()

    def _l10n_il_salary_adjustment_input_types(self):
        """מפה {code: (gross_input_type, net_input_type)} לכל 7 הסוגים - נקראת
        בכל שימוש כדי לא להניח קיום קבוע (env.ref עם raise_if_not_found=False)."""
        result = {}
        for code, key in L10N_IL_SALARY_ADJUSTMENT_TYPES.items():
            gross_type = self.env.ref(f"l10n_il_hr_payroll_account.input_il_{key}_gross", raise_if_not_found=False)
            net_type = self.env.ref(f"l10n_il_hr_payroll_account.input_il_{key}_net", raise_if_not_found=False)
            if gross_type and net_type:
                result[code] = (gross_type, net_type)
        return result

    def _compute_input_line_ids(self):
        adjustment_types = self._l10n_il_salary_adjustment_input_types()
        dedicated_type_ids = [t.id for pair in adjustment_types.values() for t in pair]

        for slip in self:
            if slip.employee_id and slip.employee_id.salary_attachment_ids and slip.date_to and slip.struct_id:
                valid_attachments = slip.employee_id.salary_attachment_ids.filtered(
                    lambda a: a.state == "open"
                        and a.other_input_type_id.code in adjustment_types
                        and a.date_start <= slip.date_to
                        and (not a.date_end or a.date_end >= slip.date_from)
                        and (not a.other_input_type_id.struct_ids or slip.struct_id in a.other_input_type_id.struct_ids)
                )
            else:
                valid_attachments = self.env["hr.salary.attachment"]
            # "נטו" מטופל בנפרד ב-compute_sheet (_l10n_il_apply_net_impact_gross_up) -
            # לא נכתב כאן בכלל, כדי שהגילום ייפתר מול הבסיס הנכון אחרי הפאס הראשון.
            gross_attachments = valid_attachments.filtered(lambda a: a.l10n_il_impact_type == "gross")

            if not slip.done_date:
                # התלוש עוד לא אושר אף פעם - עריכת טיוטה רגילה, מחשבים הכל
                # מחדש (כולל הסרה של התאמות שנסגרו/הוסרו) בדיוק כמו קודם.
                lines_to_remove = slip.input_line_ids.filtered(lambda x: x.input_type_id.id in dedicated_type_ids)
                input_line_vals = [fields.Command.unlink(line.id) for line in lines_to_remove]
                for input_type_id, attachments in gross_attachments.grouped("other_input_type_id").items():
                    gross_type, _net_type = adjustment_types[input_type_id.code]
                    amount = attachments._get_active_amount()
                    name = ", ".join(d for d in attachments.mapped("description") if d)
                    input_line_vals.append(fields.Command.create({
                        "name": name,
                        "amount": amount if not slip.credit_note else -amount,
                        "input_type_id": gross_type.id,
                    }))
                slip.update({"input_line_ids": input_line_vals})
                # שומר את מעקב-הכבר-נכלל תואם למצב הנוכחי (מוסיף מה שנכנס,
                # מוריד מה שנסגר/הוסר) - עדיין לא "ננעל", התלוש לא אושר בפועל.
                previously_tracked = slip.l10n_il_consumed_attachment_ids.filtered(
                    lambda a: a.l10n_il_impact_type == "gross")
                to_add = gross_attachments - previously_tracked
                to_remove = previously_tracked - gross_attachments
                ops = [fields.Command.link(a.id) for a in to_add] + [fields.Command.unlink(a.id) for a in to_remove]
                if ops:
                    slip.l10n_il_consumed_attachment_ids = ops
            else:
                # רענון אחרי אישור קודם ("עדכון וחישוב מחדש", ראו action_payslip_unpaid
                # ב-account_payment.py) - לא נוגעים בהתאמות שכבר חושבו כאן (גם אם
                # נסגרו/השתנו בינתיים) - מוסיפים רק התאמות פתוחות חדשות שעדיין
                # לא נכללו בתלוש הזה בכלל, גם אם הן מאותו סוג בדיוק כמו קיימת.
                new_attachments = gross_attachments - slip.l10n_il_consumed_attachment_ids
                if not new_attachments:
                    continue
                input_line_vals = []
                for input_type_id, attachments in new_attachments.grouped("other_input_type_id").items():
                    gross_type, _net_type = adjustment_types[input_type_id.code]
                    amount = attachments._get_active_amount()
                    name = ", ".join(d for d in attachments.mapped("description") if d)
                    signed_amount = amount if not slip.credit_note else -amount
                    existing_line = slip.input_line_ids.filtered(lambda i: i.input_type_id == gross_type)
                    if existing_line:
                        existing_line.amount += signed_amount
                        if name:
                            existing_line.name = f"{existing_line.name}, {name}" if existing_line.name else name
                    else:
                        input_line_vals.append(fields.Command.create({
                            "name": name, "amount": signed_amount, "input_type_id": gross_type.id,
                        }))
                if input_line_vals:
                    slip.update({"input_line_ids": input_line_vals})
                slip.l10n_il_consumed_attachment_ids = [fields.Command.link(a.id) for a in new_attachments]

    def compute_sheet(self):
        # תלוש שכבר חושב פעם אחת לא בהכרח יריץ מחדש את _compute_input_line_ids
        # (השדה מוגדר compute+store אבל @api.depends הילידי לא עוקב אחרי שינויים
        # בהתאמות שכר עצמן - רק אחרי employee_id/version_id/struct_id/date_from/
        # date_to של התלוש) - הוספת/עריכת/סגירת התאמת שכר על תלוש קיים לא הייתה
        # נכנסת בלחיצה חוזרת על "חשב תלוש". קריאה ישירה כאן (לא דרך מנגנון ה-
        # compute הרגיל) מכריחה רענון בכל לחיצה, ללא תלות בטריגר האוטומטי.
        self.filtered(lambda s: s.state == "draft")._compute_input_line_ids()
        res = super().compute_sheet()
        self._l10n_il_apply_net_impact_gross_up()
        return res

    def _l10n_il_input_amount_by_code(self, code):
        """סה"כ שהוזן עבור קוד ה-Input הנתון (סכום מדויק, לא סובל השמטת חיובי/
        שלילי) - שימושי כדי לצרף כמה קודים (למשל הצד הידני + הצד הברוטו +
        הצד הנטו של אותו סוג) בלי תלות בשם השדה הספציפי."""
        self.ensure_one()
        return sum(self.input_line_ids.filtered(lambda i: i.input_type_id.code == code).mapped("amount"))

    def _l10n_il_pension_eligible_extra(self):
        """override: סוגי התאמת השכר שסומנו ב-L10N_IL_PENSION_ELIGIBLE_TYPES
        (עמלה/תוספת אחרת) מגדילים גם הם את בסיס הפרשת הפנסיה - סוכם משני הצדדים
        (ברוטו-ישיר + נטו-מגולם, ראה _l10n_il_input_amount_by_code) של כל סוג כזה."""
        self.ensure_one()
        extra = super()._l10n_il_pension_eligible_extra()
        adjustment_types = self._l10n_il_salary_adjustment_input_types()
        for code in L10N_IL_PENSION_ELIGIBLE_TYPES:
            if code not in adjustment_types:
                continue
            extra += self._l10n_il_input_amount_by_code(code + "_GROSS")
            extra += self._l10n_il_input_amount_by_code(code + "_NET")
        return extra

    def _l10n_il_apply_net_impact_gross_up(self):
        """אחרי שהתלוש חושב פעם ראשונה (GROSS/BASIC כבר ידועים), פותרת בנפרד
        עבור כל אחד מ-7 סוגי התאמת השכר (ראו L10N_IL_SALARY_ADJUSTMENT_TYPES)
        עם התאמות שכר בסוג השפעה='נטו' (כל סימן) איזו תוספת ברוטו-שקולה
        נדרשת כדי שהנטו יעלה/ירד בדיוק בסכום שהוזן, ומזינה אותה לשורת ה-Input
        הייעודית של אותו סוג בלבד ("{type}_NET") - כל סוג עם טיפול-המס שלו:
        לנסיעות/הבראה יש תקרת פטור משותפת לכל הצדדים של אותו סוג (ידני +
        ברוטו + נטו יחד, ראו L10N_IL_EXEMPT_CEILING_METHODS ו-
        hr.payslip._l10n_il_tax_exempt_income ב-l10n_il_hr_payroll) - חלק
        מהתוספת שנפתרת כאן עשוי להיכנס 1:1 בלי מס אם עוד יש יתרת פטור לאותו
        סוג; לשאר הסוגים אין תקרה, חייב במס מלא.

        מטפלת בכל סוג בנפרד, ברצף, עם compute_sheet מלא (super, ילידי) אחרי כל
        סוג שהשתנה - כך שסוג הבא בתור פותר תמיד מול הבסיס המעודכן, והפתרון של
        כל סוג מדויק (לא קירוב) גם כשכמה סוגים פועלים יחד. עוצרת (לא רצה שוב)
        ברגע שסוג מסוים כבר מכוסה - מונע לולאה אינסופית.

        אם התלוש כבר אושר בעבר (done_date קיים - כלומר זו קריאה מ"עדכון
        וחישוב מחדש", ראו action_payslip_unpaid ב-account_payment.py) - פותרת
        רק עבור התאמות פתוחות חדשות שעוד לא נכללו בתלוש הזה (ראו
        l10n_il_consumed_attachment_ids), ומוסיפה את הדלתא הנוספת על גבי מה
        שכבר קיים - לא פותרת/נוגעת מחדש בסכום שכבר "ננעל" מחישוב קודם.
        """
        adjustment_types = self._l10n_il_salary_adjustment_input_types()
        if not adjustment_types:
            return
        for slip in self.filtered(lambda s: s.state == "draft" and s.employee_id and s.struct_id):
            is_recompute_after_confirm = bool(slip.done_date)
            valid_attachments = slip.employee_id.salary_attachment_ids.filtered(
                lambda a: a.state == "open" and a.l10n_il_impact_type == "net"
                    and a.other_input_type_id.code in adjustment_types
                    and a.date_start <= slip.date_to
                    and (not a.date_end or a.date_end >= slip.date_from)
            )
            if is_recompute_after_confirm:
                valid_attachments = valid_attachments - slip.l10n_il_consumed_attachment_ids
            else:
                # טיוטה שמעולם לא אושרה - שומרים את מעקב-הכבר-נכלל תואם למצב
                # הנוכחי (צד נטו), כך שברגע שהתלוש כן יאושר לראשונה, המעקב כבר
                # ישקף במדויק אילו התאמות-נטו נכללו (ולא ייחשבו "חדשות" בטעות
                # ברענון הבא אחרי האישור).
                previously_tracked = slip.l10n_il_consumed_attachment_ids.filtered(
                    lambda a: a.l10n_il_impact_type == "net")
                to_add = valid_attachments - previously_tracked
                to_remove = previously_tracked - valid_attachments
                ops = [fields.Command.link(a.id) for a in to_add] + [fields.Command.unlink(a.id) for a in to_remove]
                if ops:
                    slip.l10n_il_consumed_attachment_ids = ops

            targets_by_code = {}
            attachments_by_code = {}
            for input_type_id, attachments in valid_attachments.grouped("other_input_type_id").items():
                target = attachments._get_active_amount()
                if slip.credit_note:
                    target = -target
                targets_by_code[input_type_id.code] = target
                attachments_by_code[input_type_id.code] = attachments

            for code, (_gross_type, net_type) in adjustment_types.items():
                existing_line = slip.input_line_ids.filtered(lambda i: i.input_type_id == net_type)
                target_net_delta = targets_by_code.get(code, 0.0)
                if float_is_zero(target_net_delta, precision_digits=2):
                    if not is_recompute_after_confirm and existing_line:
                        # טיוטה שמעולם לא אושרה - התאמה שנסגרה/הוסרה: מותר
                        # "לאבד" את הסכום (עדיין לא ננעל שום דבר). אחרי אישור
                        # קודם - אין כאן שום דבר חדש להוסיף, לא נוגעים בקיים.
                        existing_line.unlink()
                        super(HrPayslip, slip).compute_sheet()
                    continue
                gross_line = slip.line_ids.filtered(lambda l: l.code == "GROSS")
                basic_line = slip.line_ids.filtered(lambda l: l.code == "BASIC")
                if not gross_line:
                    continue
                if is_recompute_after_confirm:
                    # תוספתי: פותרים רק את התוספת החדשה, מעל מה שכבר קיים -
                    # לא מפחיתים previous_grossup, ה"קיים" הוא הבסיס עכשיו.
                    baseline_gross_raw = gross_line.total
                else:
                    previous_grossup = existing_line.amount if existing_line else 0.0
                    baseline_gross_raw = gross_line.total - previous_grossup

                # פטור: תקרה משותפת (ידני + ברוטו + נטו) לאותו סוג בלבד - הצד
                # הידני/ברוטו (כבר קבוע, לא מושפע מהפתרון הזה) קובע כמה מהתקרה
                # כבר נוצל; היתרה זמינה לצד הנטו שנפתר כאן (remaining_exemption).
                remaining_exemption = 0.0
                this_type_already_exempt = 0.0
                ceiling_method_name = L10N_IL_EXEMPT_CEILING_METHODS.get(code)
                if ceiling_method_name:
                    ceiling = getattr(slip, ceiling_method_name)()
                    already_used = (
                        slip._l10n_il_input_amount_by_code(code)
                        + slip._l10n_il_input_amount_by_code(code + "_GROSS")
                    )
                    this_type_already_exempt = min(already_used, ceiling) if already_used > 0 else 0.0
                    remaining_exemption = max(ceiling - this_type_already_exempt, 0.0)
                elif code in L10N_IL_UNTAXED_TYPES:
                    # פטור מלא, בלי תקרה - הגילום פותר יחס 1:1 (הסכום ייכתב
                    # ישירות לקטגוריית ניכויי-רשות, לא ל-ALW/GROSS, ראו
                    # hr_salary_rule_data.xml - אין בסיס-ברוטו-חייב לחשב כאן).
                    remaining_exemption = float("inf")

                # סוגי הפטור האחרים (אם קיים) נשארים קבועים - מחושבים ישירות (לא
                # תלוי existing_line) כדי לשקף מצב עדכני אחרי שסוגים קודמים
                # באותו פאס כבר הוזנו/עודכנו.
                other_exempt = 0.0
                for other_code, other_method_name in L10N_IL_EXEMPT_CEILING_METHODS.items():
                    if other_code == code:
                        continue
                    other_ceiling = getattr(slip, other_method_name)()
                    other_total = (
                        slip._l10n_il_input_amount_by_code(other_code)
                        + slip._l10n_il_input_amount_by_code(other_code + "_GROSS")
                        + slip._l10n_il_input_amount_by_code(other_code + "_NET")
                    )
                    other_exempt += min(other_total, other_ceiling) if other_total > 0 else 0.0

                baseline_taxable_gross = baseline_gross_raw - other_exempt - this_type_already_exempt

                # סוגים עם פנסיה="כן" (עמלה/תוספת אחרת) - הגילום עצמו חייב לכלול
                # את הפרשת הפנסיה הנוספת (חלק עובד) שהתוספת הזאת תגרום ל-IL_PENS_EE
                # האמיתי לנכות בהמשך - אחרת התוצאה תמעיט בהיקף הגילום ותפספס את
                # יעד הנטו (ראה L10N_IL_PENSION_ELIGIBLE_TYPES/_l10n_il_pension_eligible_extra).
                pension_rate = 0.0
                if code in L10N_IL_PENSION_ELIGIBLE_TYPES:
                    pension_rate = slip.version_id.l10n_il_pension_employee_rate
                    if not pension_rate:
                        pension_rate = slip._rule_parameter("l10n_il_pension_min_rates")["employee"] * 100

                delta_gross = slip._l10n_il_gross_up(
                    target_net_delta, baseline_taxable_gross, basic_line.total,
                    remaining_exemption=remaining_exemption, pension_rate=pension_rate,
                )
                if is_recompute_after_confirm:
                    # תוספתי: הדלתא החדשה מצטרפת למה שכבר קיים, לא מחליפה אותו.
                    if existing_line:
                        existing_line.amount += delta_gross
                    else:
                        self.env["hr.payslip.input"].create({
                            "payslip_id": slip.id, "input_type_id": net_type.id, "amount": delta_gross,
                        })
                    slip.l10n_il_consumed_attachment_ids = [
                        fields.Command.link(a.id) for a in attachments_by_code.get(code, self.env["hr.salary.attachment"])
                    ]
                else:
                    if existing_line and abs(existing_line.amount - delta_gross) < 0.01:
                        continue  # כבר התכנס - עוד פאס לא ישנה כלום, עוצרים כאן
                    if existing_line:
                        existing_line.amount = delta_gross
                    else:
                        self.env["hr.payslip.input"].create({
                            "payslip_id": slip.id, "input_type_id": net_type.id, "amount": delta_gross,
                        })
                super(HrPayslip, slip).compute_sheet()
