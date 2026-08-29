import logging

from odoo import Command
from odoo.fields import Domain


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
    """Keep database-object ownership attached to the new add-on.

    Odoo 19 no longer stores a ``modules`` column on ``ir_model_fields``.
    Field ownership is reconstructed from the Python registry when the new
    add-on is installed, so only constraint/relation metadata needs adopting.
    """
    for model_name in ("ir.model.constraint", "ir.model.relation"):
        try:
            metadata = env[model_name]
        except KeyError:
            continue
        if "module" in metadata._fields:
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


def _remove_retired_module_record(env):
    """Hide the completed migration bridge from Apps once it is inactive."""
    old_module = env["ir.module.module"].sudo().search(
        [("name", "=", OLD_MODULE)],
        limit=1,
    )
    if not old_module:
        return
    if old_module.state in ("installed", "to install", "to upgrade", "to remove"):
        _logger.warning(
            "Keeping retired add-on record %s because its state is %s",
            OLD_MODULE,
            old_module.state,
        )
        return
    old_module.unlink()
    _logger.info("Removed retired add-on record %s from Apps", OLD_MODULE)


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


def migrate_catalog_structure(env):
    """Apply the idempotent catalog conversion on install or upgrade."""
    templates = env["product.template"].with_context(active_test=False).search(
        Domain("mdl_model_as_attribute", "=", False)
        & (
            Domain("mdl_sku_prefix", "!=", False)
            | Domain("mdl_group_default_name", "!=", False)
            | Domain("mdl_model_sku_component", "!=", False)
            | Domain("mdl_group_name_override", "!=", False)
            | Domain("mdl_group_sku_override", "!=", False)
            | Domain("mdl_model_name_override", "!=", False)
            | Domain("mdl_model_sku_override", "!=", False)
            | Domain("categ_id.mdl_sku_component", "!=", False)
        )
    )
    templates.with_context(skip_mdl_catalog_sync=True).write(
        {"mdl_catalog_managed": True}
    )

    managed_templates = env["product.template"].with_context(
        active_test=False
    ).search([("mdl_catalog_managed", "=", True)])
    manually_archived_ids = []
    for template in managed_templates:
        for product in template.product_variant_ids.filtered(
            lambda variant: (
                not variant.active and variant.mdl_catalog_allowed
            )
        ):
            if template._is_combination_possible_by_config(
                product.product_template_attribute_value_ids,
                ignore_no_variant=True,
            ):
                manually_archived_ids.append(product.id)
    converted = templates._mdl_convert_models_to_attributes()
    managed_templates._mdl_ensure_full_model_names()

    Exclusion = env["product.template.attribute.exclusion"]

    native_rules = Exclusion.search(
        [
            ("product_tmpl_id", "in", managed_templates.ids),
            ("mdl_is_catalog_condition", "=", False),
            ("product_template_attribute_value_id", "!=", False),
            ("value_ids", "!=", False),
        ]
    )
    normalized_rules = native_rules.with_context(
        mdl_defer_variant_rebuild=True
    )._mdl_expand_native_rules()
    normalized_rules._mdl_merge_duplicate_rules()
    normalized_rules = normalized_rules.exists()

    legacy_blocked = env["product.product"].with_context(
        active_test=False
    ).search(
        [
            ("product_tmpl_id", "in", managed_templates.ids),
            ("mdl_catalog_allowed", "=", False),
        ]
    )
    existing_keys = {
        (
            rule.product_tmpl_id.id,
            frozenset(rule.mdl_combination_value_ids.ids),
        )
        for rule in Exclusion.search(
            [
                ("product_tmpl_id", "in", managed_templates.ids),
                ("mdl_is_catalog_condition", "=", True),
                ("mdl_rule_type", "=", "forbidden"),
            ]
        )
    }
    exact_rule_values = []
    represented_product_ids = []
    for product in legacy_blocked:
        combination = product.product_template_attribute_value_ids.filtered(
            lambda value: value.attribute_id.create_variant != "no_variant"
        )
        if len(combination) < 2:
            _logger.info(
                "Could not convert legacy blocked product %s to a rule: "
                "its combination has fewer than two values",
                product.id,
            )
            continue
        if (
            len(combination) > 2
            and (
                product.product_tmpl_id.has_dynamic_attributes()
                or any(
                    line.attribute_id.create_variant == "no_variant"
                    for line in product.product_tmpl_id.attribute_line_ids
                )
            )
        ):
            _logger.info(
                "Could not convert legacy blocked product %s to an n-ary "
                "rule because its template uses dynamic or no-variant "
                "attributes",
                product.id,
            )
            continue
        represented_product_ids.append(product.id)
        key = (product.product_tmpl_id.id, frozenset(combination.ids))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        exact_rule_values.append(
            {
                "product_tmpl_id": product.product_tmpl_id.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [Command.set(combination.ids)],
            }
        )
    if exact_rule_values:
        Exclusion.with_context(mdl_defer_variant_rebuild=True).create(
            exact_rule_values
        )
    represented_products = env["product.product"].browse(
        represented_product_ids
    ).exists()
    represented_products.with_context(skip_mdl_catalog_sync=True).write(
        {"mdl_catalog_allowed": True}
    )
    managed_templates.with_context(
        mdl_preserve_variant_ids=True
    )._create_variant_ids()
    env["product.product"].browse(manually_archived_ids).exists().with_context(
        skip_mdl_catalog_sync=True
    ).write({"active": False})
    _remove_retired_module_record(env)

    _logger.info(
        "Converted the legacy model component on %s templates, normalized %s "
        "native rules, and migrated %s exact blocked variants",
        len(converted),
        len(normalized_rules),
        len(represented_products),
    )


def post_init_hook(env):
    migrate_catalog_structure(env)
