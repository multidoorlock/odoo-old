# Product naming, version 19.0.3.5.0

For managed product groups, `product.template.name` is an independently editable
display title. The only shared base for automatic product names is the visible,
translated `mdl_group_default_name` (Product Group Name). Ordered attribute text,
row separators and final format text are appended as before. Existing explicit
per-product, per-language name overrides remain supported.

Changing or translating the display title must not change an automatic product
name, a SKU, a variant ID or a BoM link. Copying with a custom title retains the
group-name source; the existing requirement to assign a new group SKU remains.
Legacy group/model/native name overrides are retained for compatibility but are
not naming inputs. Their old controls and the title's automatic-name Undo button
are removed. Explicit legacy Model conversion is an attribute configuration
action and is not part of this upgrade.

Text in Group uses Odoo's language dialog. Its inverse writes the existing
translated local override. Editing or resetting one language preserves the other
languages and the global attribute value; SKU components are not translated.

## Upgrade and verification

Upgrade the module using Odoo's normal module-upgrade mechanism. The pre-upgrade
migration moves the current stored effective name base into the visible group-name
field before the changed compute is loaded. It includes archived groups and stored
languages. The migration does not rebuild variants or call catalog/SKU sync, and
does not change titles, supplier records, product IDs, BoMs or component links.

Before deployment, export the current translated template configuration, automatic
and effective variant names, SKU/ID/archive state, and relevant BoM and supplier
links. Verify exact before/after equality on a test database. Run the module's
native Odoo test suite, including its new language, title, copy and migration
regressions, and perform an actual upgrade from 19.0.3.4.9. Syntax checks and the
standalone migration tests are not a substitute for these runtime checks.

## Rollback

Keep the pre-upgrade configuration export. Reverting code alone is insufficient:
the visible group-name source was deliberately materialized, and the old module
may reapply hidden overrides or legacy model text. Restore only the affected
name-source configuration from the matching export together with the old code,
after checking for edits made since deployment. Do not restore an entire
Production database to revert this naming change.
