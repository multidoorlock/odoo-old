def migrate(cr, version):
    """Retire the old module record after the replacement is installed."""
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'uninstalled'
         WHERE name = 'mdl_product_catalog'
        """
    )
