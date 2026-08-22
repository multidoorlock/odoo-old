from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_is_zero

from .l10n_il_payment_cycle_type import L10N_IL_CYCLE_TYPE_SELECTION


class AccountPayment(models.Model):
    """מרחיב תשלום חשבונאי (account.payment) כדי לתמוך בתשלומי עובדים (מחזורי
    תשלומים, פעולות וכו') לצד תשלומי ספקים/לקוחות רגילים - הכל נשמר באותה
    טבלת תשלומים אחת, באותו שדה שותף (partner_id) הקיים - בדיוק כמו שתשלומי
    ספק נוספו על גבי תשלומי לקוח: אין שדה "עובד" נפרד, רק סינון/כותרת שונים
    לאותו partner_id במסך הייעודי לשכר (ראו views/l10n_il_account_payment_views.xml).
    "העובד" של תשלום מסוים נגזר תמיד מ-partner_id.employee_ids (שדה הפוך קיים
    על res.partner מתוך hr.employee.work_contact_id). תשלום לעובד הוא תמיד
    בכיוון יוצא (Send/outbound) - אין קבלה מעובד. תשלום מתקשר לתלוש רק ברגע
    שהתלוש מאושר (ראו HrPayslip.action_validate למטה) - תשלום במצב 'טיוטה'
    עדיין לא נחשב תשלום בפועל ולא מתקשר לתלוש.
    """
    _inherit = "account.payment"

    l10n_il_batch_id = fields.Many2one(
        "l10n.il.payment.batch", string="מחזור", index=True, ondelete="set null",
        help="ריק בתשלום בודד (off-cycle).",
    )
    payslip_id = fields.Many2one(
        "hr.payslip", string="תלוש מקושר", index=True, tracking=True,
        help="התלוש שבו נכלל התשלום - מתקשר אוטומטית ברגע שהתלוש מאושר (או "
             "מיד עם היווצרותו אם נוצר ע\"י Mark as Paid). ניתן לקשר ידנית, "
             "אך חייב להיות תלוש של אותו עובד.",
    )
    # פיצול בפועל של הסכום: כל שורה = (תשלום, תלוש, סכום) - נכתב אך ורק מתוך
    # אשף סגירת תשלומי יתר (l10n_il_overpayment_closure.py), לא ניתן לקשר
    # ידנית. ריק לגמרי לתשלום רגיל (לא-מפוצל) - קיים רק כשתשלום מסוים שימש
    # בפועל לסגירת תשלום-יתר של תלוש אחר (ראו L10nIlPaymentPayslipAllocation).
    l10n_il_closure_allocation_ids = fields.One2many(
        "l10n.il.payment.payslip.allocation", "payment_id", string="פיצול בין תלושים",
    )
    l10n_il_available_closure_balance = fields.Monetary(
        string="יתרה זמינה לסגירת תשלום יתר", compute="_compute_l10n_il_available_closure_balance",
    )
    l10n_il_payslip_net_to_pay = fields.Monetary(
        related="payslip_id.l10n_il_net_to_pay", readonly=True,
        string="נטו לתשלום זמין בתלוש (למידע)",
    )
    # תיוג-בלבד (לא מוצג בטופס התשלום עצמו - ראו l10n_il_account_payment_views.xml -
    # "הסוג עצמו יופיע במחזור תשלומים", לא על התשלום) - קובע אם התשלום נוצר
    # ישר ב-state='canceled' (רק "אוכל", ראו l10n_il_payment_batch.py) ואיזה
    # עובד/י ניזון ממנו בסינונים/דוחות. "payslip" נקבע *אך ורק* אוטומטית
    # (תשלום מ-Pay Run, ראו l10n_il_payslip_run_payment_wizard.py) - לעולם לא
    # דרך בחירה ידנית.
    l10n_il_cycle_type = fields.Selection(L10N_IL_CYCLE_TYPE_SELECTION, string="סוג מחזור")

    @api.depends("payslip_id.l10n_il_net_to_pay", "l10n_il_closure_allocation_ids")
    def _compute_l10n_il_available_closure_balance(self):
        # פעם אחת שהתשלום פוצל (נוצל, ולו חלקית, לסגירת תלוש אחר) - היתרה
        # מתאפסת (אין יותר מה "לתת"), וזה גם מה שמבטיח בפועל שתשלום שכבר נוצל
        # לא ייבחר שוב בסגירה הבאה.
        for payment in self:
            if payment.l10n_il_closure_allocation_ids or not payment.payslip_id:
                payment.l10n_il_available_closure_balance = 0.0
            else:
                payment.l10n_il_available_closure_balance = max(0.0, -payment.payslip_id.l10n_il_net_to_pay)

    @api.onchange("partner_id")
    def _onchange_l10n_il_partner_employee(self):
        employee = self.partner_id.employee_ids[:1]
        if self.payslip_id and self.payslip_id.employee_id != employee:
            self.payslip_id = False

    @api.constrains("partner_id", "payslip_id")
    def _check_payslip_employee_match(self):
        for payment in self:
            if payment.payslip_id and payment.payslip_id.employee_id not in payment.partner_id.employee_ids:
                raise ValidationError("התלוש המקושר לתשלום חייב להיות תלוש של אותו עובד.")

    @api.constrains("payment_type", "partner_id")
    def _check_employee_payment_outbound(self):
        for payment in self:
            if payment.partner_id.employee_ids and payment.payment_type != "outbound":
                raise ValidationError("תשלום לעובד יכול להיות רק בכיוון יוצא (נשלח).")

    @api.model_create_multi
    def create(self, vals_list):
        payments = super().create(vals_list)
        payments._l10n_il_trigger_payslip_payment_sync()
        return payments

    def write(self, vals):
        res = super().write(vals)
        if set(vals) & {"partner_id", "state", "amount", "payslip_id"}:
            self._l10n_il_trigger_payslip_payment_sync()
        return res

    def _l10n_il_trigger_payslip_payment_sync(self):
        """כל תשלום עובד שנוצר/משתנה (למשל: הפך ל-in_process, שונה סכום, שויך/
        בוטל שיוך לתלוש) מרענן מיד את "תשלומי עובד"/"נטו לתשלום" בכל התלושים
        הפתוחים (מאושר/שולם) של אותו עובד - ראו HrPayslip._l10n_il_sync_payment_adj
        למטה. כך התלוש משקף תשלומים חדשים גם הרבה אחרי האישור, לא רק ברגע
        האישור/Mark as Paid עצמם.
        """
        partners = self.partner_id.filtered(lambda p: p.employee_ids)
        if not partners:
            return
        employees = self.env["hr.employee"].search([("work_contact_id", "in", partners.ids)])
        if not employees:
            return
        slips = self.env["hr.payslip"].search([
            ("employee_id", "in", employees.ids),
            ("state", "in", ("validated", "paid")),
        ])
        slips._l10n_il_sync_payment_adj()

    def action_l10n_il_confirm_payslip_payment(self):
        """כפתור ה"שלם" בפופאפ שנפתח מ-HrPayslip.action_payslip_paid (למטה) -
        כותבת state='in_process' ישירות (כמו ב-l10n_il_payment_batch.py
        action_create_batch, לא action_post - כדי לא להסתמך על ה-workflow
        הכללי של תשלומים, שעלול לנחות ישר על 'paid' אם היומן/חשבון-הביניים
        מוגדר accountType='asset_cash') ורק אז "סוגרת" את התלוש עצמו (state
        Mark as Paid), לא לפני - כדי שסגירת הפופאפ בלי לשלם לא תזיז את התלוש."""
        self.ensure_one()
        if self.state != "draft":
            return {"type": "ir.actions.act_window_close"}
        self.write({"state": "in_process"})
        self.payslip_id.filtered(lambda s: s.state == "validated")._l10n_il_finalize_mark_paid()
        return {"type": "ir.actions.act_window_close"}


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    # שדה אמיתי (One2many רגיל, ניתן ל-trigger graph של אודו לעקוב אחריו
    # בבטחה) - התשלומים שהתלוש הזה הוא ה-payslip_id "המקורי" שלהם. משמש כבסיס
    # ל-l10n_il_payment_ids (התצוגה המלאה, למטה) ול-l10n_il_overpayment_closed_by_ids
    # (l10n_il_overpayment_closure.py) - תלות ישירה על שדה אמיתי, לא על compute
    # אחר, כדי למנוע את אזהרת "should be searchable" של אודו.
    l10n_il_collect_payment_ids = fields.One2many(
        "account.payment", "payslip_id", string="תשלומים (מקור)")
    l10n_il_payment_ids = fields.Many2many(
        "account.payment", compute="_compute_l10n_il_payment_ids", string="תשלומים",
        help="כל תשלום שנוצר במקור בשביל התלוש הזה, וגם כל תשלום (של תלוש אחר "
             "של אותו עובד) ששימש לסגירת תשלום-היתר של התלוש הזה.",
    )

    @api.depends("l10n_il_collect_payment_ids")
    def _compute_l10n_il_payment_ids(self):
        for slip in self:
            slip.l10n_il_payment_ids = self.env["account.payment"].search([
                "|", ("payslip_id", "=", slip.id), ("l10n_il_closure_allocation_ids.payslip_id", "=", slip.id),
            ])

    def action_payslip_done(self):
        """תשלומים מתקשרים לתלוש רק כאן, ברגע האישור - לא ב-draft/create/compute_sheet
        רגיל (תלוש בטיוטה לא מחשב נטו-לתשלום בכלל). מכריחה recompute אחרי
        הקישור כדי שהנטו-לתשלום ישקף אותו לפני שהתלוש ננעל (compute_sheet
        הילידי עצמו הוא no-op אם line_ids כבר לא ריק).

        מוגדר על action_payslip_done ולא action_validate: כפתור "Confirm"/"Validate"
        בטופס עצמו (hr_payroll_account מחליף את הכיתוב ל"Validate", ראו
        views/hr_payslip_views.xml שם) קורא ל-action_payslip_done ישירות - לא
        ל-action_validate (שנשאר בשימוש רק מתפריט הרשימה, ובכל מקרה קורא
        ל-action_payslip_done באופן פנימי, ראו hr_payroll). הגדרה על
        action_validate בלבד החמיצה את הנתיב האמיתי שבו המשתמש מאשר תלוש -
        תשלומים קיימים לא-מקושרים פשוט לא נמשכו לתלוש בפועל.
        """
        to_process = self.filtered(lambda s: s.state == "draft")
        if to_process and not self.env.context.get("l10n_il_skip_overpayment_check"):
            # בדיקת תשלום-יתר רק באישור אינטראקטיבי של תלוש בודד (לא ברענון
            # עצמי אחרי "עדכון וחישוב מחדש", ולא באישור מרובה מרשימה) - ראו
            # l10n_il_overpayment_closure.py.
            if len(to_process) == 1:
                eligible = to_process._l10n_il_eligible_overpayment_closure_payments()
                if eligible:
                    wizard = self.env["l10n.il.overpayment.closure.wizard"].create({
                        "payslip_id": to_process.id,
                        "line_ids": [(0, 0, {
                            "payment_id": p.id,
                            "source_payslip_id": p.payslip_id.id,
                            "balance": p.l10n_il_available_closure_balance,
                        }) for p in eligible],
                    })
                    return {
                        "type": "ir.actions.act_window",
                        "name": "סגירת תשלומי יתר",
                        "res_model": "l10n.il.overpayment.closure.wizard",
                        "res_id": wizard.id,
                        "view_mode": "form",
                        "target": "new",
                    }
        if to_process:
            to_process._l10n_il_collect_payments()
            to_process.compute_sheet()
        return super().action_payslip_done()

    def action_payslip_unpaid(self):
        """הכפתור הילידי "Unpaid" (state: paid -> validated) לא עושה שום דבר
        מעבר לדגל הסטטוס - לא מרענן תשלומים חדשים שנוספו ולא התאמות שכר
        חדשות. בפועל המשתמש רוצה שזה יתנהג כמו "ערוך וחשב מחדש": חזרה זמנית
        לטיוטה (כתיבה ישירה, לא action_payslip_draft - לא רוצים לגעת בתנועת
        היומן המקושרת/journal entry, רק לאפשר ל-compute_sheet לרוץ, שהוא no-op
        על תלוש לא-בטיוטה) ואז אישור מחדש מלא - מרענן גם תשלומים (דרך
        action_payslip_done למעלה) וגם כל התאמות שכר חדשות (compute_sheet
        המלא, כולל _compute_input_line_ids/_l10n_il_apply_net_impact_gross_up).
        לא בודקת תשלומי-יתר כאן - זה רענון, לא אישור-לראשונה של תלוש חדש.
        """
        res = super().action_payslip_unpaid()
        self.write({"state": "draft"})
        self.with_context(l10n_il_skip_overpayment_check=True).action_payslip_done()
        return res

    def action_payslip_paid(self):
        """לחיצה בודדת (תלוש אחד) פותחת פופאפ תשלום אמיתי (עובד+תלוש נעולים,
        מחזור מוסתר, יומן/חשבון-בנק/סכום ניתנים לעריכה) במקום ליצור תשלום
        אוטומטית - "שלם" *הוא* מילוי הפופאפ הזה, לא הלחיצה על הכפתור עצמה.
        התלוש לא הופך ל-'paid' כאן - זה קורה רק אחרי שהתשלום אכן מאושר בפופאפ
        (ראו account.payment.action_l10n_il_confirm_payslip_payment למעלה),
        כדי שסגירת הפופאפ בלי לשלם לא תשאיר תלוש "שולם" בלי תשלום בפועל.

        בחירה מרובה מרשימה (כמה תלושים בבת אחת) נשארת אוטומטית כמו קודם - אין
        UX סביר לפתוח פופאפ לכל תלוש בנפרד - רק שהתשלום שנוצר כך עולה במצב
        'in_process' ("לביצוע"), לא 'paid' ישירות.
        """
        to_process = self.filtered(lambda p: p.state != "paid")
        if not to_process:
            return True
        if len(to_process) > 1:
            vals_list = to_process._l10n_il_compute_payslip_payment_vals()
            res = super(HrPayslip, to_process).action_payslip_paid()
            if vals_list:
                self.env["account.payment"].create(vals_list)
            to_process._l10n_il_close_paid_one_time_adjustments()
            return res

        slip = to_process
        net_to_pay_line = slip.line_ids.filtered(lambda l: l.code == "NET_TO_PAY")
        target = net_to_pay_line.total if net_to_pay_line else 0.0
        if target <= 0 or float_is_zero(target, precision_digits=2):
            # אין מה לשלם (עריכה שרק הורידה סכום) - אין טעם בפופאפ, פשוט
            # "סוגרים" את התלוש ישירות כמו תמיד.
            return slip._l10n_il_finalize_mark_paid()
        if not slip.employee_id or not slip.employee_id.work_contact_id:
            raise UserError("לעובד אין איש-קשר לקשר אליו תשלום.")
        # נשתמש באותה פעולה מאוחסנת (action_l10n_il_account_payment_popup)
        # שכבר משמשת בהצלחה את פופאפ "תשלום חדש" הרגיל (מסך התשלומים) - לא
        # דיקט חדש בפייתון - כדי להבטיח באופן מלא שהפופאפ ייראה בדיוק כמו
        # תשלום-עובד (עובד/חשבון-בנק ממותגים, לא ספק) ולא תשלום-ספק גנרי.
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "l10n_il_hr_payroll_account.action_l10n_il_account_payment_popup")
        action["name"] = "תשלום שכר"
        action["context"] = {
            "default_partner_id": slip.employee_id.work_contact_id.id,
            "default_partner_type": "supplier",
            "default_payment_type": "outbound",
            "default_payslip_id": slip.id,
            "default_amount": target,
            "default_partner_bank_id": slip.employee_id.primary_bank_account_id.id,
            "l10n_il_lock_payslip_fields": True,
        }
        return action

    def _l10n_il_finalize_mark_paid(self):
        """מה ש-action_payslip_paid עצמו עשה עד היום, מלבד יצירת התשלום - נדחה
        עד לאישור בפועל של התשלום בפופאפ (ראו למעלה)."""
        res = super(HrPayslip, self).action_payslip_paid()
        self._l10n_il_close_paid_one_time_adjustments()
        return res

    def _l10n_il_compute_payslip_payment_vals(self):
        """הנטו-לתשלום הנוכחי (NET_TO_PAY) כבר מייצג בדיוק "כמה עוד נשאר
        לשלם" - הוא הנטו פחות כל התשלומים שכבר מקושרים לתלוש, כולל תשלומי
        Mark as Paid קודמים (ראו _l10n_il_collect_payments - אין הבחנה בין
        off-cycle לתשלום-הפרש, הכל נספר יחד) - אז אין צורך בשום חישוב הפרש
        נפרד, פשוט יוצרים תשלום על סכום הנטו-לתשלום עצמו. רק סכום חיובי יוצר
        תשלום - נטו-לתשלום שלילי/אפס (עריכה שרק הורידה סכום) לא יוצר שום
        תשלום, נספג ישירות בתלוש. משמש רק בנתיב הבחירה-המרובה (ראו
        action_payslip_paid למעלה) - תלוש בודד עובר דרך הפופאפ.
        """
        vals_list = []
        for slip in self:
            if not slip.employee_id or not slip.employee_id.work_contact_id:
                continue
            net_to_pay_line = slip.line_ids.filtered(lambda l: l.code == "NET_TO_PAY")
            if not net_to_pay_line:
                continue
            target = net_to_pay_line.total
            if target > 0 and not float_is_zero(target, precision_digits=2):
                vals_list.append({
                    "partner_id": slip.employee_id.work_contact_id.id,
                    "partner_type": "supplier",
                    "payment_type": "outbound",
                    "amount": target,
                    "date": slip.paid_date or slip.date_to or fields.Date.today(),
                    "state": "in_process",
                    "payslip_id": slip.id,
                })
        return vals_list

    def _l10n_il_sync_payment_adj(self):
        """מסנכרנת מחדש את שורת "תשלומי עובד" (IL_PAYMENT_ADJ) ואת "נטו לתשלום"
        (NET_TO_PAY) בלבד, בכתיבה ישירה על hr.payslip.line קיימות - בלי לעבור
        דרך compute_sheet המלא (שהוא no-op על תלוש לא-בטיוטה, ראו hr_payroll -
        תלוש מאושר נשאר "נעול" בכל שאר הסכומים בכוונה, רק "כמה עוד נשאר לשלם"
        ממשיך לזוז כשתשלומים חדשים נכנסים/משתנים). נקראת מ-_l10n_il_trigger_payslip_payment_sync
        למעלה בכל פעם שתשלום עובד רלוונטי נוצר/משתנה.
        """
        slips = self.filtered(lambda s: s.state in ("validated", "paid") and s.line_ids)
        if not slips:
            return
        # native _compute_basic_net (basic_wage/gross_wage/net_wage/employer_cost)
        # במפורש מדלג על תלושים ב-state='paid' (מכוון - "נעולים" אחרי ששולם) -
        # אבל כתיבה ישירה ל-hr.payslip.line.total (למטה) מבטלת את הקאש של כל
        # שדה שתלוי ב-line_ids.total, כולל אלה - וברגע שהם מתבטלים על תלוש
        # ששולם, שום דבר לעולם לא יחשב אותם מחדש (מדלגים עליהם לצמיתות), אז
        # הם "נתקעים" על 0. שומרים את הערך הנכון מראש ומחזירים אותו לקאש
        # ידנית (env.cache.set) אחרי הכתיבה - לא דרך write/compute רגיל, כי
        # אלה שדות מחושבים-בלבד (בלי inverse), אי אפשר סתם לכתוב אליהם.
        frozen_fields = [
            slips._fields["basic_wage"], slips._fields["gross_wage"],
            slips._fields["net_wage"], slips._fields["employer_cost"],
        ]
        frozen_values = {slip.id: {f.name: slip[f.name] for f in frozen_fields} for slip in slips}
        slips._l10n_il_collect_payments()
        input_type = self.env.ref("l10n_il_hr_payroll_account.input_il_payment_adj", raise_if_not_found=False)
        for slip in slips:
            input_line = slip.input_line_ids.filtered(lambda i: i.input_type_id == input_type)
            adj_amount = input_line.amount if input_line else 0.0
            adj_line = slip.line_ids.filtered(lambda l: l.code == "IL_PAYMENT_ADJ")
            if adj_line:
                adj_line.total = adj_amount
            elif not float_is_zero(adj_amount, precision_digits=2):
                rule = self.env["hr.salary.rule"].search([
                    ("code", "=", "IL_PAYMENT_ADJ"), ("struct_id", "=", slip.struct_id.id),
                ], limit=1)
                if not rule:
                    continue
                adj_line = self.env["hr.payslip.line"].create({
                    "slip_id": slip.id, "name": rule.name, "sequence": rule.sequence,
                    "salary_rule_id": rule.id, "employee_id": slip.employee_id.id,
                    "version_id": slip.version_id.id, "quantity": 1.0, "rate": 100.0,
                    "amount": adj_amount, "total": adj_amount,
                })
            net_line = slip.line_ids.filtered(lambda l: l.code == "NET")
            net_to_pay_line = slip.line_ids.filtered(lambda l: l.code == "NET_TO_PAY")
            if net_line and net_to_pay_line:
                ded_total = sum(slip.line_ids.filtered(
                    lambda l: l.category_id.code == "IL_NET_TO_PAY_DED").mapped("total"))
                net_to_pay_line.total = net_line.total + ded_total
            # הכתיבה ל-line.total לעיל מסמנת את 4 השדות האלה כ"ממתינים לחישוב
            # מחדש" (to-compute) - invalidate/SQL גולמי לבד לא מספיקים, כי
            # ה-flush הבא עדיין ירוץ נגד ה-compute המקורי (שמדלג על 'paid')
            # ויידרוס את מה שכתבנו בחזרה ל-0. remove_to_compute מסיר אותם
            # בפועל מהתור לפני שזה קורה, ורק אז env.cache.set קובע את הערך
            # הנכון לצמיתות (באותה שיטה ש-Odoo עצמו משתמש בה כשמזינים ידנית
            # ערך לשדה מחושב-ומאוחסן בלי לעבור דרך ה-compute שלו).
            for field in frozen_fields:
                self.env.remove_to_compute(field, slip)
                self.env.cache.set(slip, field, frozen_values[slip.id][field.name], dirty=True)

    def _l10n_il_collect_payments(self):
        """קישור תשלומי העובד (account.payment, תמיד outbound) לתלוש: קורה אך
        ורק מתוך action_payslip_done (ראו למעלה) - לא ב-draft/create/compute_sheet
        רגיל. תשלום ב-state='draft' עדיין לא נחשב תשלום בפועל ולא מתקשר; כל
        תשלום אחר (לא draft, לא מבוטל/נדחה) שעדיין לא מקושר לאף תלוש מתקשר לתלוש
        הזה עכשיו. הנטו-לתשלום = הנטו פחות סכום כל התשלומים המקושרים לתלוש -
        כולל תשלומי Mark as Paid קודמים (אין הבחנה - "פתוח" הוא רק "לא מקושר
        + לא טיוטה", לא משנה המקור) - כך שבאישור/עריכה חוזרים, הנטו-לתשלום
        פשוט נסגר ל-0 אחרי ששולם במלואו.
        """
        input_type = self.env.ref("l10n_il_hr_payroll_account.input_il_payment_adj", raise_if_not_found=False)
        if not input_type:
            return
        for slip in self:
            if not slip.employee_id or not slip.employee_id.work_contact_id:
                continue
            payments = self.env["account.payment"].search([
                ("partner_id", "=", slip.employee_id.work_contact_id.id),
                ("state", "not in", ("draft", "canceled", "rejected")),
                "|", ("payslip_id", "=", False), ("payslip_id", "=", slip.id),
            ])
            input_line = slip.input_line_ids.filtered(lambda i: i.input_type_id == input_type)
            if payments:
                # תשלום לעובד הוא תמיד outbound (אכיפה: _check_employee_payment_outbound) -
                # ולכן תמיד ניכוי (שלילי) מהנטו-לתשלום.
                total = -sum(payments.mapped("amount"))
                if input_line:
                    input_line.amount = total
                else:
                    self.env["hr.payslip.input"].create({
                        "payslip_id": slip.id,
                        "input_type_id": input_type.id,
                        "amount": total,
                    })
                to_link = payments.filtered(lambda p: not p.payslip_id)
                if to_link:
                    to_link.write({"payslip_id": slip.id})
            elif input_line:
                input_line.unlink()
