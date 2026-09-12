from odoo import api, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.model
    @api.readonly
    def get_views(self, views, options=None):
        result = super().get_views(views, options=options)
        list_view = result.get('views', {}).get('list')
        if not (options or {}).get('toolbar') or not list_view:
            return result

        # Odoo's view service retains only lang and *_view_ref context when
        # loading/caching views. Resolved view identity is part of that native
        # contract and remains stable across different payslips and menus.
        prefix = 'l10n_il_hr_payroll_account.'
        linked = self.env.ref(prefix + 'view_account_payment_list_payslip_links',
                              raise_if_not_found=False)
        candidates = self.env.ref(prefix + 'view_account_payment_list_payslip_candidates',
                                  raise_if_not_found=False)
        if linked and list_view['id'] == linked.id:
            actions = self.env['ir.actions.actions']._il_payslip_payment_bindings()
            actions = [action for action in actions
                       if 'list' in action.get('binding_view_types', 'list').split(',')]
        elif candidates and list_view['id'] == candidates.id:
            actions = []
        else:
            return result

        # Replace only this request's list toolbar. Report bindings, form
        # toolbars, native Actions execution and group checks stay native.
        list_view['toolbar'] = dict(list_view.get('toolbar', {}), action=actions)
        return result
