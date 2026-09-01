from unittest.mock import Mock

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.mdl_product_groups_attributes.hooks import (
    NEW_DISPLAY_FORMAT_PARAM,
    NEW_MODULE,
    OLD_DISPLAY_FORMAT_PARAM,
    OLD_MODULE,
    _adopt_external_ids,
    _adopt_view_keys,
    _assert_no_old_namespace,
    _remove_retired_module_record,
    _retire_old_module,
    migrate_catalog_structure,
    uninstall_hook,
)


@tagged("post_install", "-at_install")
class TestHookHardening(TransactionCase):
    def _module(self, name, state):
        Modules = self.env["ir.module.module"].sudo()
        module = Modules.search([("name", "=", name)], limit=1)
        if module:
            module.write({"state": state})
            return module
        return Modules.create({"name": name, "state": state})

    def _metadata_sample(self):
        for model_name in ("ir.model.constraint", "ir.model.relation"):
            try:
                metadata = self.env[model_name]
            except KeyError:
                continue
            if "module" not in metadata._fields:
                continue
            sample = metadata.sudo().search([], limit=1)
            if sample:
                return sample
        self.skipTest("No module-owned metadata model is available")

    def _category_only_template(self, suffix):
        category = self.env["product.category"].create(
            {
                "name": f"Hook category {suffix}",
                "mdl_sku_component": f"H{suffix}",
            }
        )
        template = self.env["product.template"].create(
            {
                "name": f"Hook template {suffix}",
                "categ_id": category.id,
            }
        )
        template.with_context(skip_mdl_catalog_sync=True).write(
            {
                "mdl_catalog_managed": False,
                "mdl_group_default_name": False,
                "mdl_group_default_sku": False,
                "mdl_model_sku_component": False,
                "mdl_group_name_override": False,
                "mdl_group_sku_override": False,
                "mdl_model_name_override": False,
                "mdl_model_sku_override": False,
                "mdl_model_as_attribute": False,
            }
        )
        return template

    def _xmlid(self, module, name, record):
        return self.env["ir.model.data"].sudo().create(
            {
                "module": module,
                "name": name,
                "model": record._name,
                "res_id": record.id,
                "noupdate": True,
            }
        )

    def test_identical_external_id_collision_drops_only_old_mapping(self):
        partner = self.env["res.partner"].create({"name": "Hook target"})
        old_mapping = self._xmlid(
            OLD_MODULE,
            "hook_hardening_identical",
            partner,
        )
        new_mapping = self._xmlid(
            NEW_MODULE,
            "hook_hardening_identical",
            partner,
        )

        _adopt_external_ids(self.env)

        self.assertFalse(old_mapping.exists())
        self.assertTrue(new_mapping.exists())

    def test_different_external_id_collision_fails_without_changes(self):
        old_partner = self.env["res.partner"].create({"name": "Old target"})
        new_partner = self.env["res.partner"].create({"name": "New target"})
        old_mapping = self._xmlid(
            OLD_MODULE,
            "hook_hardening_conflict",
            old_partner,
        )
        new_mapping = self._xmlid(
            NEW_MODULE,
            "hook_hardening_conflict",
            new_partner,
        )

        with self.assertRaises(UserError):
            _adopt_external_ids(self.env)

        self.assertEqual(old_mapping.module, OLD_MODULE)
        self.assertEqual(new_mapping.module, NEW_MODULE)

    def test_view_key_collision_fails_closed(self):
        View = self.env["ir.ui.view"].sudo()
        old_view = View.create(
            {
                "name": "Old hook view",
                "type": "qweb",
                "key": f"{OLD_MODULE}.hook_hardening_view",
                "arch_db": "<t name='old_hook_view'/>",
            }
        )
        new_view = View.create(
            {
                "name": "New hook view",
                "type": "qweb",
                "key": f"{NEW_MODULE}.hook_hardening_view",
                "arch_db": "<t name='new_hook_view'/>",
            }
        )

        with self.assertRaises(UserError):
            _adopt_view_keys(self.env)

        self.assertEqual(old_view.key, f"{OLD_MODULE}.hook_hardening_view")
        self.assertEqual(new_view.key, f"{NEW_MODULE}.hook_hardening_view")

    def test_old_namespace_blocks_bridge_cleanup(self):
        partner = self.env["res.partner"].create({"name": "Namespace target"})
        self._xmlid(OLD_MODULE, "hook_hardening_residue", partner)

        with self.assertRaises(UserError):
            _assert_no_old_namespace(self.env)

    def test_old_metadata_ownership_blocks_bridge_cleanup(self):
        old_module = self._module(OLD_MODULE, "uninstalled")
        metadata = self._metadata_sample()
        metadata.write({"module": old_module.id})

        with self.assertRaisesRegex(UserError, "ownership"):
            _assert_no_old_namespace(self.env)

    def test_migration_fully_adopts_bridge_before_cleanup(self):
        old_module = self._module(OLD_MODULE, "installed")
        new_module = self._module(NEW_MODULE, "installed")
        metadata = self._metadata_sample()
        metadata.write({"module": old_module.id})

        partner = self.env["res.partner"].create({"name": "Adoption target"})
        old_mapping = self._xmlid(
            OLD_MODULE,
            "hook_hardening_migrate_adoption",
            partner,
        )
        view = self.env["ir.ui.view"].sudo().create(
            {
                "name": "Migration adoption view",
                "type": "qweb",
                "key": f"{OLD_MODULE}.hook_hardening_migrate_adoption",
                "arch_db": "<t name='migration_adoption_view'/>",
            }
        )
        params = self.env["ir.config_parameter"].sudo()
        params.search([("key", "=", NEW_DISPLAY_FORMAT_PARAM)]).unlink()
        params.set_param(OLD_DISPLAY_FORMAT_PARAM, "legacy format")

        migrate_catalog_structure(self.env)

        self.assertFalse(old_module.exists())
        self.assertEqual(old_mapping.module, NEW_MODULE)
        self.assertEqual(
            view.key,
            f"{NEW_MODULE}.hook_hardening_migrate_adoption",
        )
        self.assertEqual(metadata.module, new_module)
        self.assertFalse(params.get_param(OLD_DISPLAY_FORMAT_PARAM))
        self.assertEqual(
            params.get_param(NEW_DISPLAY_FORMAT_PARAM),
            "legacy format",
        )

    def test_category_sku_only_requires_legacy_bridge_provenance(self):
        bridge = self.env["ir.module.module"].sudo().search(
            [("name", "=", OLD_MODULE)],
            limit=1,
        )
        bridge.unlink()
        template = self._category_only_template("without-bridge")

        migrate_catalog_structure(self.env)

        self.assertFalse(template.mdl_catalog_managed)
        self.assertFalse(template.mdl_model_as_attribute)

    def test_category_sku_only_migrates_when_bridge_exists(self):
        self._module(OLD_MODULE, "uninstalled")
        self._module(NEW_MODULE, "installed")
        template = self._category_only_template("with-bridge")

        migrate_catalog_structure(self.env)

        self.assertTrue(template.mdl_catalog_managed)
        self.assertTrue(template.mdl_model_as_attribute)

    def test_explicit_catalog_fields_migrate_without_bridge(self):
        bridge = self.env["ir.module.module"].sudo().search(
            [("name", "=", OLD_MODULE)],
            limit=1,
        )
        bridge.unlink()
        template = self.env["product.template"].create(
            {"name": "Explicit hook template"}
        )
        template.with_context(skip_mdl_catalog_sync=True).write(
            {
                "mdl_catalog_managed": False,
                "mdl_group_default_name": "Explicit hook group",
                "mdl_model_sku_component": "01",
                "mdl_model_as_attribute": False,
            }
        )

        migrate_catalog_structure(self.env)

        self.assertTrue(template.mdl_catalog_managed)
        self.assertTrue(template.mdl_model_as_attribute)

    def test_bridge_cleanup_fails_closed_for_active_or_transient_state(self):
        for state in ("installed", "to install", "to upgrade", "to remove"):
            with self.subTest(state=state):
                bridge = self._module(OLD_MODULE, state)
                with self.assertRaises(UserError):
                    _remove_retired_module_record(self.env)
                self.assertTrue(bridge.exists())

    def test_migration_rejects_transient_bridge_before_catalog_changes(self):
        self._module(OLD_MODULE, "to upgrade")
        self._module(NEW_MODULE, "installed")
        template = self.env["product.template"].create(
            {"name": "Transient bridge template"}
        )
        template.with_context(skip_mdl_catalog_sync=True).write(
            {
                "mdl_catalog_managed": False,
                "mdl_group_default_name": "Must stay unchanged",
                "mdl_model_sku_component": "02",
                "mdl_model_as_attribute": False,
            }
        )

        with self.assertRaises(UserError):
            migrate_catalog_structure(self.env)

        self.assertFalse(template.mdl_catalog_managed)
        self.assertFalse(template.mdl_model_as_attribute)

    def test_retire_accepts_only_stable_rename_states(self):
        installed = Mock(state="installed")
        _retire_old_module(installed)
        installed.write.assert_called_once_with({"state": "uninstalled"})

        uninstalled = Mock(state="uninstalled")
        _retire_old_module(uninstalled)
        uninstalled.write.assert_not_called()

        for state in ("to install", "to upgrade", "to remove", "uninstallable"):
            unsafe = Mock(state=state)
            with self.assertRaises(UserError):
                _retire_old_module(unsafe)
            unsafe.write.assert_not_called()

    def test_uninstall_is_allowed_without_managed_catalog_data(self):
        self.assertFalse(
            self.env["product.template"].with_context(
                active_test=False
            ).search_count([("mdl_catalog_managed", "=", True)])
        )
        self.assertIsNone(uninstall_hook(self.env))

    def test_uninstall_blocks_managed_templates(self):
        self.env["product.template"].with_context(
            skip_mdl_catalog_sync=True
        ).create(
            {
                "name": "Managed hook template",
                "mdl_catalog_managed": True,
            }
        )

        with self.assertRaisesRegex(UserError, "קבוצות פריטים מנוהלות"):
            uninstall_hook(self.env)

    def test_uninstall_blocks_custom_rules_and_legacy_variants(self):
        first_attribute = self.env["product.attribute"].create(
            {"name": "Hook attribute A", "create_variant": "always"}
        )
        second_attribute = self.env["product.attribute"].create(
            {"name": "Hook attribute B", "create_variant": "always"}
        )
        first_value = self.env["product.attribute.value"].create(
            {"name": "A", "attribute_id": first_attribute.id}
        )
        second_value = self.env["product.attribute.value"].create(
            {"name": "B", "attribute_id": second_attribute.id}
        )
        template = self.env["product.template"].create(
            {
                "name": "Unmanaged hook template",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": first_attribute.id,
                            "value_ids": [Command.set(first_value.ids)],
                        }
                    ),
                    Command.create(
                        {
                            "attribute_id": second_attribute.id,
                            "value_ids": [Command.set(second_value.ids)],
                        }
                    ),
                ],
            }
        )
        values = template.attribute_line_ids.product_template_value_ids
        self.env["product.template.attribute.exclusion"].with_context(
            mdl_defer_variant_rebuild=True
        ).create(
            {
                "product_tmpl_id": template.id,
                "mdl_is_catalog_condition": True,
                "mdl_rule_type": "forbidden",
                "mdl_combination_value_ids": [Command.set(values.ids)],
            }
        )
        template.product_variant_id.with_context(
            skip_mdl_catalog_sync=True
        ).write({"mdl_catalog_allowed": False})

        with self.assertRaisesRegex(UserError, "כללי קטלוג מותאמים"):
            uninstall_hook(self.env)
