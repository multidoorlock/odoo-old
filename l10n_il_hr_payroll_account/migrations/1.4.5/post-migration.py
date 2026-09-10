from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Remove the discontinued generic reconciliation customization."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    view = env.ref(
        'l10n_il_hr_payroll_account.view_account_reconcile_wizard_employee_payment',
        raise_if_not_found=False,
    )
    if view:
        view.unlink()
