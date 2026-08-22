from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class L10nIlPaymentPayslipAllocation(models.Model):
    """פיצול בפועל של סכום תשלום בין תלושים - נוצר אך ורק מתוך אשף סגירת
    תשלומי יתר (_l10n_il_apply_overpayment_closure למטה), לא ניתן ליצור/לערוך
    ידנית משום מסך. קיים אך ורק עבור תשלום שבאמת "פוצל" בפועל (נוצל, ולו
    חלקית, לסגירת תלוש אחר מלבד התלוש המקורי שלו) - תשלום רגיל, לא-מפוצל,
    אין לו אף שורה כזו בכלל.

    לדוגמה: תשלום ע"ס 3000 ששייך במקור לתלוש A (עודף ב-2000), שרק 1500 ממנו
    נדרשו בפועל לסגירת תלוש B - יקבל 2 שורות: (payslip_id=A, amount=1500 -
    היתרה שעדיין "שייכת" ל-A כרגיל) ו-(payslip_id=B, amount=1500 - החלק
    שנוצל לסגירת B). הסכום הכולל של השורות תמיד שווה ל-payment_id.amount."""
    _name = "l10n.il.payment.payslip.allocation"
    _description = "פיצול תשלום בין תלושים"

    payment_id = fields.Many2one("account.payment", required=True, ondelete="cascade", index=True)
    payslip_id = fields.Many2one("hr.payslip", required=True, index=True)
    amount = fields.Monetary(string="סכום")
    currency_id = fields.Many2one(related="payment_id.currency_id")


class HrPayslip(models.Model):
    """"תשלום יתר" (סטטוס תשלום=overpaid, נטו-לתשלום שלילי) - קורה למשל כשתלוש
    כבר שולם במלואו ואז נוספה לו התאמת שכר שלילית וחושב מחדש: הנטו ירד, אבל
    כבר שולם הנטו הישן (הגבוה יותר), אז "נטו לתשלום" יוצא שלילי - "יתרה" (הסכום
    ששולם יותר מידי) = -l10n_il_net_to_pay. מטופל כמקרה מיוחד: ברגע שתלוש חדש
    (אותו עובד) מאושר, נבדק אם יש תשלומים פתוחים (של תלושי-תשלום-יתר, לא נוצלו
    עדיין לסגירה) שהנטו-לתשלום של התלוש החדש מספיק גדול לכסות - ראה
    L10nIlOverpaymentClosureWizard למטה ו-account_payment.py.action_payslip_done.

    הקישור עצמו הוא ברמת **תשלום, עם פיצול סכום אמיתי** (לא סתם קישור בוליאני):
    תשלום שנוצר במקור עבור תלוש A (העודף) עשוי "לשמש גם" לסגירת תלוש B - רק
    בחלק מסכומו, אם זה כל מה שנדרש (ראו L10nIlPaymentPayslipAllocation למעלה).
    אי אפשר לקשר תשלום ידנית ליותר מתלוש אחד בשום מסך רגיל - הפיצול נוצר אך
    ורק מתוך _l10n_il_apply_overpayment_closure למטה.
    """
    _inherit = "hr.payslip"

    l10n_il_overpayment_closed_by_ids = fields.Many2many(
        "hr.payslip", compute="_compute_l10n_il_overpayment_closed_by_ids", string="נסגר על ידי תלוש",
        help="תלוש(ים) שדרכם נסגרה יתרת תשלום-היתר של התלוש הזה - נגזר מהתשלומים "
             "המקוריים של התלוש הזה שחלק מסכומם שימש לסגירת תלוש אחר.",
    )

    @api.depends("l10n_il_collect_payment_ids.l10n_il_closure_allocation_ids.payslip_id")
    def _compute_l10n_il_overpayment_closed_by_ids(self):
        for payslip in self:
            allocations = payslip.l10n_il_collect_payment_ids.l10n_il_closure_allocation_ids
            payslip.l10n_il_overpayment_closed_by_ids = allocations.payslip_id - payslip

    @api.depends("l10n_il_overpayment_closed_by_ids")
    def _compute_l10n_il_payment_status(self):
        super()._compute_l10n_il_payment_status()
        for payslip in self:
            if payslip.l10n_il_overpayment_closed_by_ids:
                payslip.l10n_il_payment_status = "paid"

    def _l10n_il_eligible_overpayment_closure_payments(self):
        """תשלומים פתוחים (יתרה זמינה > 0, עדיין לא פוצלו כלל) של אותו עובד -
        כל אחד ניתן לבחירה, גם אם היתרה שלו (מלוא היתרה הפתוחה של תלוש-המקור
        שלו) גדולה מהנטו-לתשלום הזמין כאן: הסגירה עשויה להיות חלקית (רק חלק
        מהיתרה ננעל כאן, השאר נשאר פתוח לתלוש-מקור שלו, ל"סגירה" עתידית) - ראו
        _l10n_il_apply_overpayment_closure למטה."""
        self.ensure_one()
        if not self.employee_id or not self.employee_id.work_contact_id or self.l10n_il_net_to_pay <= 0:
            return self.env["account.payment"]
        candidates = self.env["account.payment"].search([
            ("partner_id", "=", self.employee_id.work_contact_id.id),
            ("state", "not in", ("draft", "canceled", "rejected")),
        ])
        return candidates.filtered(lambda p: p.l10n_il_available_closure_balance > 0.01)

    def action_open_l10n_il_overpayment_closed_by(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "נסגר על ידי תלוש",
            "res_model": "hr.payslip",
            "domain": [("id", "in", self.l10n_il_overpayment_closed_by_ids.ids)],
            "view_mode": "list,form",
        }

    def _l10n_il_apply_overpayment_closure(self, closure_lines):
        """closure_lines: שורות (l10n.il.overpayment.closure.wizard.line) שנבחרו
        לסגירה. כל תשלום נצרך רק עד כמה שבאמת דרוש - עד היתרה הפתוחה של תלוש-
        המקור שלו, וגם לא יותר ממה שנשאר "מקום" עבורו בתלוש הסוגר (הנטו-לתשלום
        הזמין כאן, פחות מה שכבר נוצל ע"י שורות קודמות באותה קריאה). מה שלא נדרש
        נשאר "שייך" לתלוש המקור כרגיל (שורת הקצאה נוספת, לא מוזז). סגירה חלקית
        מותרת לגמרי: אם היתרה הפתוחה של תלוש-מקור גדולה מהמקום שנשאר כאן, רק
        חלק ממנה נסגר עכשיו - השאר נשאר פתוח לתלוש-מקור שלו, ל"סגירה" עתידית
        ע"י תלוש אחר. מוודאת תחילה (בלי לכתוב שום דבר) שאף תשלום לא "מיותר"
        (כבר כוסה במלואו ע"י תשלומים קודמים באותה קבוצה, או שכבר אין מקום
        בתלוש הסוגר) - ורק אז יוצרת את שורות ההקצאה ואת input הסגירה בפועל."""
        self.ensure_one()
        if not closure_lines:
            return
        by_source = {}
        for line in closure_lines:
            by_source.setdefault(line.source_payslip_id, self.env["l10n.il.overpayment.closure.wizard.line"])
            by_source[line.source_payslip_id] |= line
        plan = []
        total_closure = 0.0
        slip_remaining = self.l10n_il_net_to_pay
        for source, lines in by_source.items():
            remaining_need = -source.l10n_il_net_to_pay
            for line in lines.sorted("id"):
                payment = line.payment_id
                if slip_remaining <= 0.01:
                    raise UserError(
                        f"תשלום {payment.name or payment.id} לא נדרש - הנטו לתשלום הזמין בתלוש הזה "
                        "כבר נוצל במלואו ע\"י תשלומים אחרים שנבחרו. יש לבטל את הסימון שלו."
                    )
                if remaining_need <= 0.01:
                    raise UserError(
                        f"תשלום {payment.name or payment.id} לא נדרש לסגירת תלוש {source.name} - "
                        "היתרה כבר כוסתה במלואה ע\"י תשלומים אחרים שנבחרו. יש לבטל את הסימון שלו."
                    )
                take = min(payment.amount, remaining_need, slip_remaining)
                leftover = payment.amount - take
                plan.append((payment, source, take, leftover))
                remaining_need -= take
                slip_remaining -= take
                total_closure += take
        Allocation = self.env["l10n.il.payment.payslip.allocation"]
        for payment, source, take, leftover in plan:
            if not float_is_zero(leftover, precision_digits=2):
                Allocation.create({"payment_id": payment.id, "payslip_id": source.id, "amount": leftover})
            Allocation.create({"payment_id": payment.id, "payslip_id": self.id, "amount": take})
        if not float_is_zero(total_closure, precision_digits=2):
            input_type = self.env.ref("l10n_il_hr_payroll_account.input_il_overpayment_closure")
            self.env["hr.payslip.input"].create({
                "payslip_id": self.id, "input_type_id": input_type.id, "amount": total_closure,
            })


class L10nIlOverpaymentClosureWizard(models.TransientModel):
    """פופאפ שנפתח בלחיצה על "אישור" (Confirm) כשנמצאו תשלומים פתוחים (של
    תלושי תשלום-יתר) של אותו עובד שניתן לנצל לסגירה באמצעות התלוש הזה - בחירה
    מרובה (checkbox לכל תשלום), עם בדיקה שהסכום הכולל שנבחר לא עולה על הנטו-
    לתשלום הזמין."""
    _name = "l10n.il.overpayment.closure.wizard"
    _description = "סגירת תשלומי יתר"

    payslip_id = fields.Many2one("hr.payslip", required=True, readonly=True)
    net_to_pay = fields.Monetary(related="payslip_id.l10n_il_net_to_pay", readonly=True, string="נטו לתשלום זמין")
    currency_id = fields.Many2one(related="payslip_id.currency_id")
    line_ids = fields.One2many(
        "l10n.il.overpayment.closure.wizard.line", "wizard_id", string="תשלומים פתוחים לסגירה")
    total_selected = fields.Monetary(string="סה״כ נבחר לסגירה", compute="_compute_total_selected")
    l10n_il_fewer_payments_warning = fields.Char(
        string="אזהרה", compute="_compute_l10n_il_fewer_payments_warning")

    @api.depends("line_ids.selected", "line_ids.balance")
    def _compute_total_selected(self):
        for wizard in self:
            wizard.total_selected = sum(wizard.line_ids.filtered("selected").mapped("balance"))

    @api.depends("line_ids.selected")
    def _compute_l10n_il_fewer_payments_warning(self):
        # אזהרה מייעצת-בלבד (לא חוסמת): אם נבחרו 2+ תשלומים מאותו תלוש-מקור,
        # אבל תשלום בודד אחר (זמין, לא בהכרח נבחר) היה מכסה את כל היתרה לבד -
        # מציעה אותו כדרך פשוטה יותר, לפני שמאשרים.
        for wizard in self:
            messages = []
            by_source = {}
            for line in wizard.line_ids.filtered("selected"):
                by_source.setdefault(line.source_payslip_id, wizard.line_ids.browse())
                by_source[line.source_payslip_id] |= line
            for source, lines in by_source.items():
                if len(lines) < 2:
                    continue
                need = -source.l10n_il_net_to_pay
                single_candidates = wizard.line_ids.filtered(
                    lambda l, source=source, need=need: l.source_payslip_id == source and l.balance >= need - 0.01
                )
                if single_candidates:
                    best = single_candidates.sorted("balance")[0]
                    messages.append(f"ניתן לסגור את תלוש {source.name} עם תשלום בודד בלבד: {best.payment_id.display_name}.")
                else:
                    messages.append(f"תלוש {source.name} נבחר עם {len(lines)} תשלומים - ודא שזו הדרך הטובה ביותר.")
            wizard.l10n_il_fewer_payments_warning = " ".join(messages) if messages else False

    def action_confirm(self):
        self.ensure_one()
        selected = self.line_ids.filtered("selected")
        self.payslip_id._l10n_il_apply_overpayment_closure(selected)
        return self.payslip_id.with_context(l10n_il_skip_overpayment_check=True).action_payslip_done()

    def action_skip(self):
        self.ensure_one()
        return self.payslip_id.with_context(l10n_il_skip_overpayment_check=True).action_payslip_done()


class L10nIlOverpaymentClosureWizardLine(models.TransientModel):
    _name = "l10n.il.overpayment.closure.wizard.line"
    _description = "שורת תשלום לסגירת תשלום יתר"

    wizard_id = fields.Many2one("l10n.il.overpayment.closure.wizard", required=True, ondelete="cascade")
    payment_id = fields.Many2one("account.payment", string="תשלום", required=True, readonly=True)
    payment_amount = fields.Monetary(
        string="סכום התשלום", related="payment_id.amount", readonly=True,
        help="הסכום המלא של התשלום עצמו - לא כל הסכום הזה בהכרח ישמש לסגירה (ראו יתרה לסגירה, ברמת התלוש-מקור).")
    source_payslip_id = fields.Many2one("hr.payslip", string="תלוש מקור", readonly=True)
    balance = fields.Monetary(
        string="יתרה לסגירה", readonly=True,
        help="היתרה הפתוחה הכוללת של תלוש-המקור - זהה לכל שורות התשלום ששייכות לאותו תלוש-מקור (לא סכום-לתשלום נפרד לכל שורה).")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    selected = fields.Boolean(string="לסגור")
