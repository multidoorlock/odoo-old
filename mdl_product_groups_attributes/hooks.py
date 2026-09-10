import logging

from odoo import Command
from odoo.exceptions import UserError
from odoo.fields import Domain


_logger = logging.getLogger(__name__)

OLD_MODULE = "mdl_product_catalog"
NEW_MODULE = "mdl_product_groups_attributes"
OLD_DISPLAY_FORMAT_PARAM = f"{OLD_MODULE}.variant_display_format"
NEW_DISPLAY_FORMAT_PARAM = f"{NEW_MODULE}.variant_display_format"
SUPPORTED_RENAME_STATES = frozenset({"installed", "uninstalled"})
UNSAFE_TRANSIENT_STATES = frozenset(
    {"to install", "to upgrade", "to remove"}
)


def _adopt_external_ids(env):
    """Move records owned by the retired add-on to the replacement add-on."""
    ModelData = env["ir.model.data"].sudo()
    old_mappings = ModelData.search([("module", "=", OLD_MODULE)])
    duplicates = ModelData
    mappings_to_adopt = ModelData
    conflicts = []

    # Preflight every collision before changing anything.  This makes a
    # partially migrated namespace impossible even if a caller catches the
    # UserError instead of letting the surrounding transaction roll back.
    for old_mapping in old_mappings:
        new_mapping = ModelData.search(
            [
                ("module", "=", NEW_MODULE),
                ("name", "=", old_mapping.name),
            ],
            limit=1,
        )
        if not new_mapping:
            mappings_to_adopt |= old_mapping
            continue
        old_target = (old_mapping.model, old_mapping.res_id)
        new_target = (new_mapping.model, new_mapping.res_id)
        if old_target == new_target:
            duplicates |= old_mapping
            continue
        conflicts.append(
            (
                old_mapping.name,
                old_target,
                new_target,
            )
        )

    if conflicts:
        details = "; ".join(
            "%s: %s,%s != %s,%s"
            % (name, old_model, old_res_id, new_model, new_res_id)
            for name, (old_model, old_res_id), (new_model, new_res_id)
            in conflicts
        )
        raise UserError(
            env._(
                "לא ניתן להשלים את החלפת התוסף: מזהי XML קיימים בשני "
                "המרחבים ומצביעים לרשומות שונות. %(details)s",
                details=details,
            )
        )

    duplicates.unlink()
    mappings_to_adopt.write({"module": NEW_MODULE})


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
    View = env["ir.ui.view"].sudo()
    views = View.search(
        [("key", "=like", f"{old_prefix}%")]
    )
    key_changes = []
    collisions = []
    for view in views:
        new_key = new_prefix + view.key[len(old_prefix):]
        collision = View.search(
            [("key", "=", new_key), ("id", "!=", view.id)],
            limit=1,
        )
        if collision:
            collisions.append((view.key, view.id, new_key, collision.id))
        else:
            key_changes.append((view, new_key))

    if collisions:
        details = "; ".join(
            "%s (view %s) -> %s (view %s)"
            % (old_key, old_id, new_key, new_id)
            for old_key, old_id, new_key, new_id in collisions
        )
        raise UserError(
            env._(
                "לא ניתן להשלים את החלפת התוסף: מפתח תצוגה חדש כבר "
                "שייך לתצוגה אחרת. %(details)s",
                details=details,
            )
        )

    for view, new_key in key_changes:
        view.key = new_key


def _assert_no_old_namespace(env):
    """Fail before bridge cleanup if any retired XML namespace survives."""
    residues = []
    ModelData = env["ir.model.data"].sudo()
    old_mappings = ModelData.search(
        [("module", "=", OLD_MODULE)],
        limit=5,
    )
    if old_mappings:
        residues.append(
            "XML IDs: "
            + ", ".join(
                f"{mapping.module}.{mapping.name}"
                for mapping in old_mappings
            )
        )

    old_view_keys = env["ir.ui.view"].sudo().search(
        [("key", "=like", f"{OLD_MODULE}.%")],
        limit=5,
    )
    if old_view_keys:
        residues.append(
            "view keys: "
            + ", ".join(old_view_keys.mapped("key"))
        )

    if env["ir.config_parameter"].sudo().search_count(
        [("key", "=", OLD_DISPLAY_FORMAT_PARAM)],
        limit=1,
    ):
        residues.append(f"parameter: {OLD_DISPLAY_FORMAT_PARAM}")

    old_module = env["ir.module.module"].sudo().search(
        [("name", "=", OLD_MODULE)],
        limit=1,
    )
    if old_module:
        for model_name in ("ir.model.constraint", "ir.model.relation"):
            try:
                metadata = env[model_name]
            except KeyError:
                continue
            if "module" not in metadata._fields:
                continue
            owned_metadata = metadata.sudo().search(
                [("module", "=", old_module.id)],
                limit=5,
            )
            if owned_metadata:
                residues.append(
                    "%s ownership: %s"
                    % (
                        model_name,
                        ", ".join(map(str, owned_metadata.ids)),
                    )
                )

    if residues:
        raise UserError(
            env._(
                "לא ניתן להסיר את גשר ההעברה לפני שכל הרשומות הועברו "
                "מהמרחב הטכני הישן: %(details)s",
                details="; ".join(residues),
            )
        )


def _validate_old_module_state(old_module):
    """Allow only stable states supported by the two-stage rename bridge."""
    state = old_module.state
    if state not in SUPPORTED_RENAME_STATES:
        state_kind = (
            "transient" if state in UNSAFE_TRANSIENT_STATES else "unsupported"
        )
        raise UserError(
            old_module.env._(
                "לא ניתן להחליף את התוסף %(module)s כשהוא במצב %(state)s "
                "(%(state_kind)s). יש להשלים או לבטל תחילה את פעולת "
                "ההתקנה/השדרוג/ההסרה.",
                module=OLD_MODULE,
                state=state,
                state_kind=state_kind,
            )
        )


def _retire_old_module(old_module):
    """Mark the installed bridge retired after all ownership was adopted."""
    _validate_old_module_state(old_module)
    state = old_module.state
    if state == "installed":
        old_module.write({"state": "uninstalled"})


def _adopt_display_format(env):
    params = env["ir.config_parameter"].sudo()
    old_value = params.get_param(OLD_DISPLAY_FORMAT_PARAM)
    if old_value and not params.get_param(NEW_DISPLAY_FORMAT_PARAM):
        params.set_param(NEW_DISPLAY_FORMAT_PARAM, old_value)
    params.search([("key", "=", OLD_DISPLAY_FORMAT_PARAM)]).unlink()


def _adopt_retired_module(env, old_module, new_module):
    """Fully transfer bridge ownership and verify it before retirement."""
    _validate_old_module_state(old_module)
    if not new_module:
        raise UserError(
            env._(
                "לא ניתן להעביר את %(old)s ללא רשומת המודול החלופי "
                "%(new)s.",
                old=OLD_MODULE,
                new=NEW_MODULE,
            )
        )

    _adopt_display_format(env)
    _adopt_external_ids(env)
    _adopt_model_metadata(env, old_module, new_module)
    _adopt_view_keys(env)
    _assert_no_old_namespace(env)
    _retire_old_module(old_module)


def _remove_retired_module_record(env):
    """Hide the completed migration bridge from Apps once it is inactive."""
    old_module = env["ir.module.module"].sudo().search(
        [("name", "=", OLD_MODULE)],
        limit=1,
    )
    if not old_module:
        return
    _validate_old_module_state(old_module)
    if old_module.state == "installed":
        raise UserError(
            env._(
                "לא ניתן להסיר את גשר ההעברה %(module)s כשהוא עדיין "
                "מותקן. העברת הבעלות למודול החלופי לא הושלמה.",
                module=OLD_MODULE,
            )
        )
    _assert_no_old_namespace(env)
    old_module.unlink()
    _logger.info("Removed retired add-on record %s from Apps", OLD_MODULE)


def pre_init_hook(env):
    """Replace the previous technical module without duplicating its records."""
    modules = env["ir.module.module"].sudo()
    old_module = modules.search([("name", "=", OLD_MODULE)], limit=1)
    new_module = modules.search([("name", "=", NEW_MODULE)], limit=1)

    if not old_module:
        _adopt_display_format(env)
        return
    _adopt_retired_module(env, old_module, new_module)
    _logger.info(
        "Replaced installed add-on %s with %s",
        OLD_MODULE,
        NEW_MODULE,
    )


def migrate_catalog_structure(env):
    """Apply the idempotent catalog conversion on install or upgrade."""
    modules = env["ir.module.module"].sudo()
    old_module = modules.search([("name", "=", OLD_MODULE)], limit=1)
    legacy_bridge_present = bool(old_module)
    if old_module:
        new_module = modules.search([("name", "=", NEW_MODULE)], limit=1)
        _adopt_retired_module(env, old_module, new_module)

    explicit_catalog_domain = (
        Domain("mdl_sku_prefix", "!=", False)
        | Domain("mdl_group_default_name", "!=", False)
        | Domain("mdl_model_sku_component", "!=", False)
        | Domain("mdl_group_name_override", "!=", False)
        | Domain("mdl_group_sku_override", "!=", False)
        | Domain("mdl_model_name_override", "!=", False)
        | Domain("mdl_model_sku_override", "!=", False)
    )
    if legacy_bridge_present:
        # A category SKU alone is legacy provenance only when the old bridge
        # record proves this database went through the retired add-on.
        explicit_catalog_domain |= Domain(
            "categ_id.mdl_sku_component", "!=", False
        )
    templates = env["product.template"].with_context(active_test=False).search(
        Domain("mdl_model_as_attribute", "=", False)
        & explicit_catalog_domain
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


def uninstall_hook(env):
    """Block removal while catalog data still depends on this add-on."""
    managed_template_count = (
        env["product.template"]
        .sudo()
        .with_context(active_test=False)
        .search_count([("mdl_catalog_managed", "=", True)])
    )
    catalog_rule_count = env[
        "product.template.attribute.exclusion"
    ].sudo().search_count([("mdl_is_catalog_condition", "=", True)])
    legacy_blocked_variant_count = (
        env["product.product"]
        .sudo()
        .with_context(active_test=False)
        .search_count([("mdl_catalog_allowed", "=", False)])
    )

    if not any(
        (
            managed_template_count,
            catalog_rule_count,
            legacy_blocked_variant_count,
        )
    ):
        return

    raise UserError(
        env._(
            "לא ניתן להסיר את Multi Doorlock - Product Groups & Attributes "
            "כל עוד קיימים נתונים שמסתמכים עליו. נמצאו %(templates)s "
            "קבוצות פריטים מנוהלות, %(rules)s כללי קטלוג מותאמים ו-%(variants)s "
            "וריאנטים חסומים מהמבנה הישן. יש לנקות או להעביר את הנתונים "
            "תחילה; ההסרה נעצרה כדי למנוע אובדן מידע.",
            templates=managed_template_count,
            rules=catalog_rule_count,
            variants=legacy_blocked_variant_count,
        )
    )
