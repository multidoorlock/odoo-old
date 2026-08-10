from odoo import fields, models
from odoo.tools.sql import drop_view_if_exists


class L10nIlEmployeeBalanceReport(models.Model):
    """דוח יתרת עובד: שורה אחת לכל עובד, מול התלוש האחרון שאושר לו (state
    validated/paid) - כמה שולם עד כה על התלוש הזה, כמה היה אמור להשתלם עליו,
    וכמות/סכום התשלומים הפתוחים של העובד שעדיין לא קושרו לאף תלוש."""
    _name = "l10n.il.employee.balance.report"
    _description = "דוח יתרת עובד"
    _auto = False
    _order = "employee_id"

    employee_id = fields.Many2one("hr.employee", string="עובד", readonly=True)
    payslip_id = fields.Many2one("hr.payslip", string="תלוש אחרון שאושר", readonly=True)
    company_id = fields.Many2one("res.company", string="חברה", readonly=True)
    currency_id = fields.Many2one(related="company_id.currency_id")
    date_from = fields.Date(string="מתאריך", readonly=True)
    date_to = fields.Date(string="עד תאריך", readonly=True)
    net = fields.Monetary(string="כמה היה אמור להשתלם", readonly=True)
    paid_so_far = fields.Monetary(string="כמה שולם עד כה", readonly=True)
    net_to_pay = fields.Monetary(string="יתרה לתשלום על התלוש", readonly=True)
    open_payment_count = fields.Integer(string="תשלומים פתוחים (לא מקושרים)", readonly=True)
    open_payment_total = fields.Monetary(string="סה״כ תשלומים פתוחים", readonly=True)

    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS (
                SELECT
                    p.id AS id,
                    p.employee_id AS employee_id,
                    p.id AS payslip_id,
                    p.company_id AS company_id,
                    p.date_from AS date_from,
                    p.date_to AS date_to,
                    COALESCE(net_line.total, 0) AS net,
                    COALESCE(net_line.total, 0) - COALESCE(ntp_line.total, 0) AS paid_so_far,
                    COALESCE(ntp_line.total, 0) AS net_to_pay,
                    COALESCE(op.cnt, 0) AS open_payment_count,
                    COALESCE(op.total, 0) AS open_payment_total
                FROM (
                    SELECT DISTINCT ON (employee_id) id, employee_id, company_id, date_from, date_to
                    FROM hr_payslip
                    WHERE state IN ('validated', 'paid')
                    ORDER BY employee_id, date_to DESC, id DESC
                ) p
                LEFT JOIN LATERAL (
                    SELECT SUM(l.total) AS total FROM hr_payslip_line l
                    WHERE l.slip_id = p.id AND l.code = 'NET'
                ) net_line ON true
                LEFT JOIN LATERAL (
                    SELECT SUM(l.total) AS total FROM hr_payslip_line l
                    WHERE l.slip_id = p.id AND l.code = 'NET_TO_PAY'
                ) ntp_line ON true
                LEFT JOIN LATERAL (
                    SELECT COUNT(*) AS cnt, SUM(ap.amount) AS total
                    FROM account_payment ap
                    JOIN hr_employee e ON e.work_contact_id = ap.partner_id
                    WHERE e.id = p.employee_id
                        AND ap.payslip_id IS NULL
                        AND ap.state NOT IN ('draft', 'canceled', 'rejected')
                ) op ON true
            )
        """)
