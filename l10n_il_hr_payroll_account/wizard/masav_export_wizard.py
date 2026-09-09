import base64
import re
from datetime import date
from decimal import Decimal

from odoo import fields, models, _
from odoo.exceptions import UserError

from ..lib.masav import (
    MasavFile,
    MasavPayment,
    MasavValidationError,
    build_masav_file,
)


class IlMasavExportWizard(models.TransientModel):
    _name = 'il.masav.export.wizard'
    _description = 'Create MASAV Payment File'

    batch_payment_id = fields.Many2one(
        'account.batch.payment', required=True, readonly=True, ondelete='cascade')
    company_id = fields.Many2one(
        related='batch_payment_id.company_id', readonly=True)
    payment_date = fields.Date(related='batch_payment_id.date', readonly=True)
    line_ids = fields.One2many(
        'il.masav.export.wizard.line', 'wizard_id', string='תשלומים')
    file_data = fields.Binary(string='קובץ מס״ב', readonly=True)
    filename = fields.Char(readonly=True)

    def _masav_payment(self, payment):
        employee = payment._il_employee()
        if not employee:
            raise UserError(_(
                'התשלום %s אינו מקושר לעובד ולכן לא ניתן לכלול אותו בקובץ מס״ב.',
                payment.display_name,
            ))
        bank = payment.partner_bank_id
        if not bank:
            raise UserError(_(
                'לא הוגדר חשבון בנק בתשלום %s של העובד %s.',
                payment.display_name, employee.name,
            ))
        clearing_number = bank.il_masav_clearing_number
        if not clearing_number:
            raise UserError(_(
                'בחשבון הבנק של העובד %s יש להגדיר Clearing Number הכולל '
                'בדיוק 5 ספרות: 2 ספרות קוד בנק ו-3 ספרות מספר סניף.',
                employee.name,
            ))
        sanitized_account = (bank.sanitized_acc_number or '').upper()
        if sanitized_account.startswith('IL') and len(sanitized_account) == 23:
            account_number = sanitized_account[-13:].lstrip('0') or '0'
        else:
            account_number = ''.join(
                character for character in sanitized_account if character.isdigit())
            if len(account_number) > 9:
                account_number = account_number.lstrip('0') or '0'
        identification = ''.join(
            character for character in (employee.identification_id or '')
            if character.isdigit())
        if not identification:
            raise UserError(_('לא הוגדר מספר זיהוי לעובד %s.', employee.name))
        return MasavPayment(
            bank_code=clearing_number[:2],
            branch_code=clearing_number[2:],
            account_number=account_number,
            beneficiary_id=identification,
            beneficiary_name=employee.name,
            amount=Decimal(str(payment.amount)),
            reference=str(payment.id),
            period_from=payment.date,
            period_to=payment.date,
        )

    def action_generate(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_('יש לבחור לפחות תשלום אחד.'))
        payments = selected_lines.payment_id
        invalid = payments.filtered(
            lambda payment: (
                payment.batch_payment_id != self.batch_payment_id
                or payment.state not in ('in_process', 'paid')
            ))
        if invalid:
            raise UserError(_(
                'ניתן לכלול רק תשלומים מהמחזור הנוכחי שבסטטוס לביצוע או שולם.'
            ))
        company = self.company_id
        if not company.il_masav_institution_number or not company.il_masav_sender_number:
            raise UserError(_(
                'יש להגדיר בהגדרות השכר מספר מוסד / נושא ומספר מוסד שולח של מס״ב.'
            ))
        try:
            content = build_masav_file(MasavFile(
                institution_number=company.il_masav_institution_number,
                sender_number=company.il_masav_sender_number,
                institution_name=company.name,
                payment_date=self.payment_date,
                creation_date=date.today(),
                payments=[self._masav_payment(payment) for payment in payments],
                hebrew_code=company.il_masav_hebrew_code,
            ))
        except MasavValidationError as error:
            raise UserError(_('לא ניתן ליצור את קובץ המס״ב: %s', str(error))) from error

        safe_name = re.sub(
            r'[^A-Za-z0-9_.-]+', '_', self.batch_payment_id.name or 'payments')
        filename = f'MASAV_{safe_name}_{self.payment_date:%Y%m%d}.txt'
        encoded = base64.b64encode(content)
        payments.write({
            'il_masav_file': encoded,
            'il_masav_filename': filename,
            'il_masav_generated_on': fields.Datetime.now(),
        })
        self.batch_payment_id.write({
            'export_file': encoded,
            'export_filename': filename,
            'export_file_create_date': fields.Date.today(),
        })
        self.write({'file_data': encoded, 'filename': filename})
        return {
            'type': 'ir.actions.act_url',
            'url': (
                f'/web/content?model={self._name}&id={self.id}'
                '&field=file_data&filename_field=filename&download=true'
            ),
            'target': 'self',
        }


class IlMasavExportWizardLine(models.TransientModel):
    _name = 'il.masav.export.wizard.line'
    _description = 'MASAV Payment Selection'
    _order = 'payment_id'

    wizard_id = fields.Many2one(
        'il.masav.export.wizard', required=True, ondelete='cascade')
    selected = fields.Boolean(string='נבחר', default=True)
    payment_id = fields.Many2one(
        'account.payment', string='תשלום', required=True, readonly=True)
    partner_id = fields.Many2one(
        related='payment_id.partner_id', string='עובד', readonly=True)
    date = fields.Date(related='payment_id.date', string='תאריך', readonly=True)
    partner_bank_id = fields.Many2one(
        related='payment_id.partner_bank_id', string='חשבון בנק', readonly=True)
    currency_id = fields.Many2one(related='payment_id.currency_id', readonly=True)
    amount = fields.Monetary(
        related='payment_id.amount', string='סכום', currency_field='currency_id',
        readonly=True)
    state = fields.Selection(
        related='payment_id.state', string='סטטוס', readonly=True)
