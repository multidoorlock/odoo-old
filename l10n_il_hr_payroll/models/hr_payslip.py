from odoo import api, fields, models
from odoo.tools import float_is_zero


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    l10n_il_net_to_pay = fields.Monetary(
        string="נטו לתשלום", compute="_compute_l10n_il_net_to_pay", store=True,
        help="הנטו הרגיל (NET) בתוספת/בניכוי התאמות שמשפיעות רק על הסכום שבפועל "
             "משולם לעובד - תשלומים (מפרעות וכו') ו/או התאמות שכר ששולמו כבר מחוץ "
             "לתלוש. כאשר אין התאמות כאלה, נטו לתשלום שווה לנטו הרגיל.",
    )
    l10n_il_payment_status = fields.Selection(
        [("paid", "שולם"), ("partial", "שולם חלקית"), ("unpaid", "לא שולם"), ("overpaid", "תשלום יתר")],
        string="סטטוס תשלום", compute="_compute_l10n_il_payment_status", store=True,
        help="שולם (ירוק): נטו לתשלום = 0. שולם חלקית (צהוב): נטו לתשלום קטן מהנטו וגדול מ-0. "
             "לא שולם (אדום): נטו לתשלום שווה או גדול מהנטו. תשלום יתר (כתום): נטו לתשלום שלילי "
             "(שולם יותר מהנטו בפועל). נטו=0 וגם נטו-לתשלום=0 (למשל תלוש שעדיין לא חושב) - ריק, בלי סטטוס.",
    )

    @api.depends("line_ids.total")
    def _compute_l10n_il_net_to_pay(self):
        to_compute_payslips = self.filtered(lambda p: p.state != "cancel").with_prefetch()
        line_values = (to_compute_payslips._origin)._get_line_values(["NET_TO_PAY"])
        for payslip in to_compute_payslips:
            payslip.l10n_il_net_to_pay = line_values["NET_TO_PAY"][payslip._origin.id]["total"]

    @api.depends("l10n_il_net_to_pay", "net_wage")
    def _compute_l10n_il_payment_status(self):
        for payslip in self:
            net_to_pay = payslip.l10n_il_net_to_pay
            net = payslip.net_wage
            if float_is_zero(net_to_pay, precision_digits=2) and float_is_zero(net, precision_digits=2):
                # אין עדיין שום דבר לשלם (למשל תלוש שעוד לא חושב) - אין סטטוס
                # בכלל, לא "שולם" (0=0 זה לא הישג, זה פשוט ריק).
                payslip.l10n_il_payment_status = False
            elif float_is_zero(net_to_pay, precision_digits=2):
                payslip.l10n_il_payment_status = "paid"
            elif net_to_pay < 0:
                payslip.l10n_il_payment_status = "overpaid"
            elif net_to_pay < net:
                payslip.l10n_il_payment_status = "partial"
            else:
                payslip.l10n_il_payment_status = "unpaid"
