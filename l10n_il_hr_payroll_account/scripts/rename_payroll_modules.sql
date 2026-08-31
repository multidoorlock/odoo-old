\set ON_ERROR_STOP on

-- Run once, before starting Odoo with the renamed module directories.
-- The transaction is all-or-nothing and preserves the installed module IDs,
-- XML IDs, views, dependencies and historical business records.
BEGIN;

DO $$
DECLARE
    old_name text;
    new_name text;
    old_id integer;
    new_id integer;
    new_state text;
    new_xmlid_count integer;
BEGIN
    FOR old_name, new_name IN
        SELECT * FROM (VALUES
            ('mdl_payroll', 'l10n_il_hr_payroll'),
            ('mdl_payroll_payments', 'l10n_il_hr_payroll_account')
        ) AS module_names(old_name, new_name)
    LOOP
        SELECT id INTO old_id FROM ir_module_module WHERE name = old_name;
        SELECT id, state INTO new_id, new_state
          FROM ir_module_module WHERE name = new_name;

        IF old_id IS NULL THEN
            IF new_id IS NULL THEN
                RAISE NOTICE 'Neither % nor % exists; fresh installation will create %',
                    old_name, new_name, new_name;
            ELSE
                RAISE NOTICE 'Module % is already renamed', new_name;
            END IF;
            CONTINUE;
        END IF;

        IF new_id IS NOT NULL THEN
            SELECT count(*) INTO new_xmlid_count
              FROM ir_model_data WHERE module = new_name;
            IF new_state NOT IN ('uninstalled', 'uninstallable') OR new_xmlid_count != 0 THEN
                RAISE EXCEPTION
                    'Cannot merge target module % (state %, XML IDs %)',
                    new_name, new_state, new_xmlid_count;
            END IF;
            DELETE FROM ir_module_module WHERE id = new_id;
        END IF;

        UPDATE ir_module_module_dependency
           SET name = new_name
         WHERE name = old_name;
        UPDATE ir_module_module_exclusion
           SET name = new_name
         WHERE name = old_name;
        UPDATE ir_model_data
           SET module = new_name
         WHERE module = old_name;
        UPDATE ir_ui_view
           SET key = new_name || substring(key FROM length(old_name) + 1)
         WHERE key LIKE old_name || '.%';
        UPDATE ir_asset
           SET path = new_name || substring(path FROM length(old_name) + 1)
         WHERE path LIKE old_name || '/%';
        UPDATE ir_module_module
           SET name = new_name
         WHERE id = old_id;

        RAISE NOTICE 'Renamed module % to % (preserved ID %)',
            old_name, new_name, old_id;
    END LOOP;
END $$;

COMMIT;
