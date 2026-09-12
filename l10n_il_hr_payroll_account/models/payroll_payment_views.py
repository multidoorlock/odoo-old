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
        if list_view['id'] in {view.id for view in (linked, candidates) if view}:
            actions = []
        else:
            return result

        # Allocation editing uses native row Save and a selected header
        # button. Do not mix payment document actions into this list.
        list_view['toolbar'] = dict(list_view.get('toolbar', {}), action=actions)
        return result
