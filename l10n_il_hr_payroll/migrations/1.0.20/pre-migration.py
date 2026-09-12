"""Remove the retired morning-only view before the removed field is validated."""
from odoo import SUPERUSER_ID, api


XMLID = 'l10n_il_hr_payroll.hr_attendance_overtime_rule_morning_view_form'


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "SELECT model, res_id FROM ir_model_data WHERE module = %s AND name = %s",
        ['l10n_il_hr_payroll', 'hr_attendance_overtime_rule_morning_view_form'],
    )
    reference = cr.fetchone()
    if not reference:
        return
    if reference[0] != 'ir.ui.view':
        raise RuntimeError('The retired morning-only XML ID no longer identifies a view.')
    view_id = reference[1]
    cr.execute('SELECT model FROM ir_ui_view WHERE id = %s', [view_id])
    view = cr.fetchone()
    if view and view[0] != 'hr.attendance.overtime.rule':
        raise RuntimeError('The retired morning-only view now targets another model.')
    cr.execute('SELECT id FROM ir_ui_view WHERE inherit_id = %s ORDER BY id', [view_id])
    children = cr.fetchall()
    if children:
        # This change is scoped to our one view; preserve every other view.
        raise RuntimeError(
            'Review inherited views before removing the morning-only extension: %s' % children)
    cr.execute('SELECT id FROM ir_ui_view_custom WHERE ref_id = %s', [view_id])
    if cr.fetchall():
        raise RuntimeError('Review user customizations before removing the morning-only view.')
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False, 'no_cow': True})
    retired = env['ir.ui.view'].browse(view_id).exists()
    if retired:
        # The standard unlink clears view caches and its external identifier.
        # Do not activate uninstall-mode cascading or website copy-on-unlink.
        if hasattr(retired, '_get_specific_views') and retired._get_specific_views():
            raise RuntimeError('Review website copies before removing the morning-only view.')
        retired.unlink()
    else:
        env['ir.model.data'].search([
            ('module', '=', 'l10n_il_hr_payroll'),
            ('name', '=', 'hr_attendance_overtime_rule_morning_view_form'),
        ]).unlink()
