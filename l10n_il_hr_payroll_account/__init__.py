from . import models


def post_init_hook(env):
    """Backfill: זורעת את 3 שורות מחזור-התשלומים הקבועות (אוכל/מפרעה/הלוואה)
    לכל עובד קיים שנוצר לפני הפיצ'ר הזה - עובדים חדשים נזרעים אוטומטית
    (ראו hr_employee.py.create)."""
    env["hr.employee"].search([])._l10n_il_seed_payment_cycle_lines()
