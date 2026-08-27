import logging


_logger = logging.getLogger(__name__)

OLD_MODULE = "mdl_product_catalog"
NEW_MODULE = "mdl_product_groups_attributes"
OLD_DISPLAY_FORMAT_PARAM = f"{OLD_MODULE}.variant_display_format"
NEW_DISPLAY_FORMAT_PARAM = f"{NEW_MODULE}.variant_display_format"


def _adopt_external_ids(env):
    """Move records owned by the retired add-on to the replacement add-on."""
    env.cr.execute(
        """
        UPDATE ir_model_data AS old_data
           SET module = %s
         WHERE old_data.module = %s
           AND NOT EXISTS (
                SELECT 1
                  FROM ir_model_data AS new_data
                 WHERE new_data.module = %s
                   AND new_data.name = old_data.name
           )
        """,
        (NEW_MODULE, OLD_MODULE, NEW_MODULE),
    )


def _adopt_model_metadata(env, old_module, new_module):
    """Keep field and database-object ownership attached to the new add-on."""
    env.cr.execute(
        """
        UPDATE ir_model_fields
           SET modules = REPLACE(modules, %s, %s)
         WHERE modules LIKE %s
        """,
        (OLD_MODULE, NEW_MODULE, f"%{OLD_MODULE}%"),
    )
    for model_name in ("ir.model.constraint", "ir.model.relation"):
        try:
            metadata = env[model_name]
        except KeyError:
            continue
        if metadata and "module" in metadata._fields:
            metadata.sudo().search(
                [("module", "=", old_module.id)]
            ).write({"module": new_module.id})


def _adopt_view_keys(env):
    """Replace cached view keys that still contain the old XML-ID namespace."""
    old_prefix = f"{OLD_MODULE}."
    new_prefix = f"{NEW_MODULE}."
    views = env["ir.ui.view"].sudo().search(
        [("key", "like", f"{old_prefix}%")]
    )
    for view in views:
        new_key = new_prefix + view.key[len(old_prefix):]
        if not env["ir.ui.view"].sudo().search_count(
            [("key", "=", new_key), ("id", "!=", view.id)]
        ):
            view.key = new_key


def _adopt_display_format(env):
    params = env["ir.config_parameter"].sudo()
    old_value = params.get_param(OLD_DISPLAY_FORMAT_PARAM)
    if old_value and not params.get_param(NEW_DISPLAY_FORMAT_PARAM):
        params.set_param(NEW_DISPLAY_FORMAT_PARAM, old_value)
    params.search([("key", "=", OLD_DISPLAY_FORMAT_PARAM)]).unlink()


def pre_init_hook(env):
    """Replace the previous technical module without duplicating its records."""
    modules = env["ir.module.module"].sudo()
    old_module = modules.search([("name", "=", OLD_MODULE)], limit=1)
    new_module = modules.search([("name", "=", NEW_MODULE)], limit=1)

    _adopt_display_format(env)
    if not old_module or not new_module:
        return

    _adopt_external_ids(env)
    _adopt_model_metadata(env, old_module, new_module)
    _adopt_view_keys(env)
    old_module.write({"state": "uninstalled"})
    _logger.info(
        "Replaced installed add-on %s with %s",
        OLD_MODULE,
        NEW_MODULE,
    )
