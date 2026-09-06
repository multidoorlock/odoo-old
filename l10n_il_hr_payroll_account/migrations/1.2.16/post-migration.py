def migrate(cr, version):
    cr.execute("""
        UPDATE hr_payslip_input_type
           SET il_net_adjustment_treatment = 'gross_up'
         WHERE il_net_adjustment_treatment = 'direct_net'
    """)
    cr.execute("""
        UPDATE hr_salary_attachment
           SET il_net_adjustment_treatment = 'gross_up'
         WHERE il_net_adjustment_treatment = 'direct_net'
    """)
    cr.execute("""
        UPDATE hr_payslip_input
           SET il_net_adjustment_treatment = 'gross_up'
         WHERE il_net_adjustment_treatment = 'direct_net'
    """)
    cr.execute("""
        UPDATE hr_salary_rule
           SET active = FALSE
         WHERE code = 'IL_ADJUSTMENT_NET_DIRECT'
    """)
