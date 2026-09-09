"""One-time recovery for a database where both payroll module names exist.

Run while the normal Odoo service is stopped::

    ./odoo-bin shell -d DATABASE < \
        l10n_il_hr_payroll_account/scripts/reset_duplicated_payroll_modules.py

Take a PostgreSQL backup first.  The script deliberately refuses to run when
it finds payslips, salary adjustments, or an
unexpected installed module which depends on one of the payroll modules.

Employees and ``hr.attendance`` rows are standard Odoo business records.  The
script records their counts, resets only the four old/new payroll modules,
installs the two canonical modules, and verifies that those counts did not
change.  Payroll-specific values on employee versions are recreated with the
module defaults and may need to be configured again.
"""

from odoo.exceptions import UserError


OLD_MODULES = (
    'mdl_payroll_payments',
    'mdl_payroll',
)
NEW_MODULES = (
    'l10n_il_hr_payroll_account',
    'l10n_il_hr_payroll',
)
ALL_MODULES = OLD_MODULES + NEW_MODULES


def count_if_loaded(model_name):
    if model_name not in env.registry:
        return 0
    return env[model_name].with_context(active_test=False).search_count([])


def module_summary(modules):
    return ', '.join(
        '%s=%s' % (module.name, module.state)
        for module in modules.sorted('name')
    ) or '(none)'


Module = env['ir.module.module'].sudo()
modules = Module.search([('name', 'in', ALL_MODULES)])
print('Payroll module state before reset:', module_summary(modules))

# This recovery path is intentionally only for a database without payroll
# transactions.  It is safer to stop than to guess when production data exists.
protected_counts = {
    'hr.payslip': count_if_loaded('hr.payslip'),
    'hr.salary.attachment': count_if_loaded('hr.salary.attachment'),
}
nonempty = {
    model: count for model, count in protected_counts.items() if count
}
if nonempty:
    raise UserError(
        'Payroll reset stopped because payroll data exists: %s'
        % nonempty
    )

before = {
    'employees': env['hr.employee'].with_context(
        active_test=False).search_count([]),
    'attendances': env['hr.attendance'].search_count([]),
}
print('Protected records before reset:', before)

installed = modules.filtered(
    lambda module: module.state in ('installed', 'to upgrade'))
unexpected = installed.downstream_dependencies().filtered(
    lambda module: module.state in ('installed', 'to upgrade')
    and module.name not in ALL_MODULES
)
if unexpected:
    raise UserError(
        'Payroll reset stopped because other installed modules depend on it: %s'
        % module_summary(unexpected)
    )

# Uninstall all installed variants in one operation.  Odoo determines the
# correct dependency order and rebuilds the registry before returning.
if installed:
    print('Uninstalling:', module_summary(installed))
    installed.button_immediate_uninstall()

# Verify that the uninstallation did not leave owned XML records under either
# old namespace.  If it did, stop before installing a second copy again.
old_xmlids = env['ir.model.data'].sudo().search_count([
    ('module', 'in', OLD_MODULES),
])
if old_xmlids:
    raise UserError(
        'Reset stopped: %s XML IDs still use an old payroll module name.'
        % old_xmlids
    )

# Refresh the applications list now that only the canonical directories are
# present, then install both canonical modules.  button_immediate_install()
# rebuilds the registry, so this is safe in an Odoo shell.
Module = env['ir.module.module'].sudo()
Module.update_list()
targets = Module.search([('name', 'in', NEW_MODULES)])
missing = set(NEW_MODULES) - set(targets.mapped('name'))
if missing:
    raise UserError(
        'Canonical module directories are missing from addons_path: %s'
        % sorted(missing)
    )

not_ready = targets.filtered(
    lambda module: module.state not in ('uninstalled', 'installed'))
if not_ready:
    raise UserError(
        'Canonical modules are in an unexpected state: %s'
        % module_summary(not_ready)
    )

to_install = targets.filtered(lambda module: module.state == 'uninstalled')
if to_install:
    print('Installing canonical modules:', module_summary(to_install))
    to_install.button_immediate_install()

# Remove the now-uninstalled technical rows for the obsolete names so they no
# longer appear in Apps.  Their module-owned data was already removed above.
Module = env['ir.module.module'].sudo()
obsolete = Module.search([('name', 'in', OLD_MODULES)])
bad_obsolete = obsolete.filtered(
    lambda module: module.state not in ('uninstalled', 'uninstallable'))
if bad_obsolete:
    raise UserError(
        'Old modules are unexpectedly still active: %s'
        % module_summary(bad_obsolete)
    )
obsolete.unlink()
env.cr.commit()

after = {
    'employees': env['hr.employee'].with_context(
        active_test=False).search_count([]),
    'attendances': env['hr.attendance'].search_count([]),
}
if after != before:
    raise UserError(
        'Protected record counts changed. Before: %s; after: %s'
        % (before, after)
    )

final_modules = env['ir.module.module'].sudo().search([
    ('name', 'in', NEW_MODULES),
])
wrong_state = final_modules.filtered(lambda module: module.state != 'installed')
if len(final_modules) != len(NEW_MODULES) or wrong_state:
    raise UserError(
        'Canonical payroll modules are not fully installed: %s'
        % module_summary(final_modules)
    )

print('Protected records after reset:', after)
print('Final payroll module state:', module_summary(final_modules))
print('SUCCESS: payroll modules were reset without deleting employees or attendances.')
