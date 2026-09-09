# Per-language variant names

Version 19.0.3.4.0 adds **Custom Name in This Language** to both variant forms.
The standard Odoo language button opens the installed languages. A non-empty
value replaces that variant's generated name only in that exact language.
Clearing one language restores its generated name without clearing other
languages. **Automatic Name** remains visible beside the editable field.

The effective name is used in the form title, variant list, display name,
product selection/search, and newly generated sale descriptions. Sales use
the order's customer language. Existing sale descriptions are not recomputed
just because an override changes. Odoo's supplier-specific names retain their
existing precedence in a supplier context. Internal references are unchanged.

## Storage and integration

- `mdl_name_overrides`: sparse JSON map on `product.product`; exact language
  keys, no `en_US` fallback, and normal product access rules. ORM writes keep
  access checks, cache invalidation, and transaction retry behavior.
- `mdl_name_override`: non-stored translated Char with compute/inverse and a
  field-scoped adapter for Odoo's `get_field_translations` and
  `_update_field_translations`. No custom browser widget or global translation
  patch is needed. The adapter is necessary because native Char translation
  falls back to English, and native False writes clear all translations.
- `mdl_generated_name` remains the existing automatic helper;
  `mdl_automatic_name` and `mdl_effective_name` render in the current language.
- Searches extract only the active language from JSON, using a parameterized
  expression inside the ORM query, preserving record rules and result limits.
- Missing languages, including languages activated later, keep automatic names.
  Archived variants retain overrides. Duplicates start without overrides.

No data migration is required. Upgrading creates an empty nullable column;
existing products keep their automatic names until an override is entered.

## Verification

The Odoo TransactionCase `TestVariantNameOverride` covers form writes, the
native translation RPC, English/Hebrew/Arabic isolation, newly activated French,
clearing and cache reloads, searches, source changes, SKU preservation, customer
language, access checks, invalid input, archiving, and copy behavior.

Run after upgrading the module in a development database:

```bash
odoo-bin -d "$ODOO_TEST_DATABASE" -u mdl_product_groups_attributes \
  --test-tags /mdl_product_groups_attributes:TestVariantNameOverride \
  --stop-after-init
```

In the UI, open a managed product variant, enter an English custom name, open
the language button, and enter a Hebrew name while leaving Arabic blank.
Switch the user language to verify the custom names and Arabic automatic name.
Clear Hebrew using the language dialog and verify English remains customized.
