from odoo import api, fields, models
from odoo.tools import float_is_zero


class HrPayslipRun(models.Model):
    """"שלם" (Mark as Paid) על מחזור-תלושים (Pay Run) - במקום ליצור תשלום
    אוטומטית לכל התלושים בבת אחת (כמו היום), פותח פופאפ "מחזור תשלומים" -
    מציג את כל העובדים המקושרים ל-Pay Run הזה עם סכום ניתן-לעריכה (ברירת
    מחדל = הנטו-לתשלום שלהם) ותיבת "נכלל" - משלם רק את מי שנכלל, בדיוק כמו
    אשף מחזור תשלום רגיל (l10n.il.payment.batch.wizard). תלושים בלי נטו-
    לתשלום זמין (0 או שלילי) לא מוצגים בכלל - נסגרים ישירות בלי פופאפ, כמו
    בתלוש בודד (ראו HrPayslip.action_payslip_paid, account_payment.py)."""
    _inherit = "hr.payslip.run"

    def action_paid(self):
        slips = self.mapped("slip_ids").filtered(lambda s: s.state != "paid")
        owing = slips.filtered(
            lambda s: s.l10n_il_net_to_pay > 0 and not float_is_zero(s.l10n_il_net_to_pay, precision_digits=2))
        not_owing = slips - owing
        if not_owing:
            not_owing._l10n_il_finalize_mark_paid()
        if not owing:
            return True
        wizard = self.env["l10n.il.payslip.run.payment.wizard"].create({
            "payslip_run_id": self.id if len(self) == 1 else False,
            "line_ids": [(0, 0, {
                "payslip_id": slip.id,
                "amount": slip.l10n_il_net_to_pay,
                "partner_bank_id": slip.employee_id.primary_bank_account_id.id,
            }) for slip in owing],
        })
        return {
            "type": "ir.actions.act_window",
            "name": "תשלום מחזור תלושים",
            "res_model": "l10n.il.payslip.run.payment.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }


class L10nIlPayslipRunPaymentWizard(models.TransientModel):
    _name = "l10n.il.payslip.run.payment.wizard"
    _description = "תשלום מחזור תלושים"

    payslip_run_id = fields.Many2one("hr.payslip.run", string="מחזור תלושים")
    journal_id = fields.Many2one("account.journal", string="יומן")
    payment_method_line_id = fields.Many2one(
        "account.payment.method.line", string="אמצעי תשלום",
        domain="[('journal_id', 'in', [journal_id, False])]",
    )
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    set_all_amount = fields.Monetary(string="הגדר לכולם")
    line_ids = fields.One2many(
        "l10n.il.payslip.run.payment.wizard.line", "wizard_id", string="עובדים")

    @api.onchange("journal_id")
    def _onchange_journal_id(self):
        if self.payment_method_line_id.journal_id and self.payment_method_line_id.journal_id != self.journal_id:
            self.payment_method_line_id = False

    def action_set_all_amount(self):
        self.ensure_one()
        self.line_ids.filtered("included").write({"amount": self.set_all_amount})
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": "תשלום מחזור תלושים",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_confirm(self):
        self.ensure_one()
        included = self.line_ids.filtered(lambda l: l.included and not float_is_zero(l.amount, precision_digits=2))
        if not included:
            included_all = self.line_ids.filtered("included")
            included_all.mapped("payslip_id")._l10n_il_finalize_mark_paid()
            return {"type": "ir.actions.act_window_close"}
        # תשלום דרך Pay Run *הוא* יצירת מחזור-תשלומים - סוג "תלוש" נקבע תמיד
        # אוטומטית (לעולם לא ניתן לבחירה ידנית, ראו l10n_il_payment_cycle_type.py) -
        # כך שגם מחזורי Payrun מופיעים במסך "מחזורים והוראות" הרגיל.
        batch = self.env["l10n.il.payment.batch"].create({
            "name": self.payslip_run_id.name if self.payslip_run_id else "תשלום Pay Run",
            "date": fields.Date.context_today(self),
            "l10n_il_batch_kind": "payment",
        })
        payment_vals = {}
        if self.journal_id:
            payment_vals["journal_id"] = self.journal_id.id
        if self.payment_method_line_id:
            payment_vals["payment_method_line_id"] = self.payment_method_line_id.id
        for line in included:
            self.env["account.payment"].create({
                **payment_vals,
                "partner_id": line.employee_id.work_contact_id.id,
                "partner_type": "supplier",
                "partner_bank_id": line.partner_bank_id.id,
                "payment_type": "outbound",
                "amount": line.amount,
                "payslip_id": line.payslip_id.id,
                "l10n_il_batch_id": batch.id,
                "l10n_il_cycle_type": "payslip",
                "state": "in_process",
            })
        self.line_ids.filtered("included").mapped("payslip_id")._l10n_il_finalize_mark_paid()
        return {"type": "ir.actions.act_window_close"}


class L10nIlPayslipRunPaymentWizardLine(models.TransientModel):
    _name = "l10n.il.payslip.run.payment.wizard.line"
    _description = "שורת עובד בתשלום מחזור תלושים"

    wizard_id = fields.Many2one("l10n.il.payslip.run.payment.wizard", required=True, ondelete="cascade")
    payslip_id = fields.Many2one("hr.payslip", string="תלוש", required=True, readonly=True)
    employee_id = fields.Many2one(related="payslip_id.employee_id", string="עובד", readonly=True)
    employee_bank_account_ids = fields.Many2many(
        related="employee_id.bank_account_ids", string="חשבונות בנק של העובד")
    partner_bank_id = fields.Many2one(
        "res.partner.bank", string="חשבון בנק",
        domain="[('id', 'in', employee_bank_account_ids)]",
    )
    net_to_pay = fields.Monetary(related="payslip_id.l10n_il_net_to_pay", readonly=True, string="נטו לתשלום זמין")
    currency_id = fields.Many2one(related="wizard_id.currency_id")
    amount = fields.Monetary(string="סכום")
    included = fields.Boolean(string="נכלל", default=True)
