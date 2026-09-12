(async () => {
    const cfg = window.hrNavigationSimulation;
    const visible = (node) => Boolean(node && node.getClientRects().length);
    const all = (selector, root = document) => [...root.querySelectorAll(selector)].filter(visible);
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    async function wait(check, message, timeout = 15000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            const result = check();
            if (result) return result;
            await pause(80);
        }
        throw new Error(`Navigation UI timeout: ${message}\n${document.body.innerText.slice(-4500)}`);
    }
    const number = (text) => Number(text.replace(/[^\d.\-]/g, ''));
    const mainList = () => all('.o_list_view .o_list_table')[0];
    const rows = () => mainList() ? all('.o_data_row', mainList()) : [];
    const rowWith = (text) => rows().find((row) => row.textContent.includes(text));
    const groups = () => mainList() ? all('.o_group_header', mainList()) : [];
    async function clickName(name) {
        let button = all(`button[name='${name}']`).find((node) => !node.closest('.modal'));
        if (!button && all('.o_form_view .o_button_more').length) {
            all('.o_form_view .o_button_more')[0].click();
            button = await wait(() => all(`button[name='${name}']`)[0], `overflow button ${name}`);
        }
        assert(button, `Native button ${name} must be reachable`);
        button.click();
    }
    async function expandGroups() {
        for (const group of groups()) {
            if (!group.classList.contains('o_group_open')) {
                group.click();
                await wait(() => group.classList.contains('o_group_open'), 'employee group expanded');
            }
        }
    }
    function assertMoneyCell(cell, expected, message) {
        assert(cell && number(cell.textContent) === expected, `${message}: ${cell?.textContent}`);
        assert(visible(cell) && cell.getBoundingClientRect().width >= 55, `${message} has readable width`);
        const range = document.createRange();
        range.selectNodeContents(cell);
        const text = range.getBoundingClientRect();
        const box = cell.getBoundingClientRect();
        assert(text.width <= box.width + 2, `${message} numeric value must fit its cell`);
    }
    async function backToForm(buttonName) {
        window.history.back();
        await wait(() => all('.o_form_view')[0] && all(`button[name='${buttonName}']`)[0], 'return to native form');
    }

    if (cfg.scenario === 'batch') {
        const field = await wait(() => all(".o_form_view .o_field_widget[name='payment_ids']")[0], 'native batch payments tab');
        await wait(() => all('.o_data_row', field).length === 3, 'three native flat tab rows');
        assert(!all('.o_group_header', field).length, 'Batch tab must remain a flat native list');
        assert(all("button[name='action_il_open_grouped_payments']").length === 1, 'One batch payments smart button');
        assert(all("button[name='action_il_print_employee_payments']").length === 1, 'Employee report is reachable');
        assert(!field.textContent.includes('UI-NAV-OUTSIDE'), 'Flat tab excludes another batch payment');
        const flatFooter = all('tfoot .o_list_number', field).find((cell) => number(cell.textContent) === cfg.flatTotal);
        assertMoneyCell(flatFooter, cfg.flatTotal, 'Native tab total');
        await clickName('action_il_open_grouped_payments');
        await wait(() => groups().length === 2, 'two employee groups without an outer Payments group');
        const groupA = groups().find((group) => group.textContent.includes(cfg.employeeA));
        const groupB = groups().find((group) => group.textContent.includes(cfg.employeeB));
        assert(groupA && groupB, 'Both native employee group names must be visible');
        assertMoneyCell(all('.o_list_number', groupA).find((cell) => number(cell.textContent) === 600), 600, 'Employee A subtotal');
        assertMoneyCell(all('.o_list_number', groupB).find((cell) => number(cell.textContent) === 900), 900, 'Employee B subtotal');
        assertMoneyCell(all('tfoot .o_list_number', mainList()).find((cell) => number(cell.textContent) === 1500), 1500, 'Batch grand total');
        await expandGroups();
        await wait(() => rows().length === 3, 'all grouped native payments expanded');
        assert(['UI-NAV-ALPHA', 'UI-NAV-BETA', 'UI-NAV-GAMMA'].every(rowWith), 'All three batch payments present');
        assert(!rowWith('UI-NAV-OUTSIDE'), 'Smart button must preserve the exact batch domain');
        assertMoneyCell(rowWith('UI-NAV-ALPHA').querySelector("td[name='amount']"), 100, 'Payment amount');
        assert(!mainList().querySelector("th[data-name='journal_id']"), 'No Journal column on employee payments');
        assert(!mainList().querySelector("th[data-name='payment_method_line_id']"), 'No Payment Method column');

        // Open and cancel the native custom-filter dialog without changing data.
        all('.o_searchview_dropdown_toggler')[0].click();
        (await wait(() => all('.o_add_custom_filter')[0], 'native custom filter menu')).click();
        const filterDialog = await wait(() => all('.modal')[0], 'native custom filter dialog');
        const filterCancel = all('.modal-footer button', filterDialog).find((button) =>
            /^(Cancel|Discard|Close|ביטול|בטל|סגור)$/.test(button.textContent.trim()));
        assert(filterCancel, 'Native filter dialog has a visible cancellation control');
        filterCancel.click();
        await wait(() => !all('.modal').length, 'custom filter cancelled');
        assert(rows().length === 3, 'Cancelling a filter preserves all batch rows');

        const input = all('.o_searchview_input')[0];
        input.focus();
        input.value = 'UI-NAV-ALPHA';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await wait(() => all('.o_searchview_autocomplete')[0], 'native memo search suggestions');
        input.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', bubbles: true, cancelable: true}));
        await wait(() => groups().length === 1, 'memo search narrows employee groups');
        await expandGroups();
        await wait(() => rows().length === 1 && rowWith('UI-NAV-ALPHA'), 'native memo search result');
        rowWith('UI-NAV-ALPHA').querySelector('.o_list_record_selector input').click();
        (await wait(() => all(".o_cp_action_menus button[data-hotkey='u']")[0], 'native Actions menu')).click();
        (await wait(() => all('.o_menu_item').find((item) => /^(Export|ייצוא|יצוא)$/.test(item.textContent.trim())), 'native Export action')).click();
        const exportDialog = await wait(() => all('.o_export_data_dialog')[0], 'native export field picker');
        assert(all('.o_export_search_input', exportDialog).length === 1, 'Export fields are searchable');
        assert(all("input[name='o_export_format_name']", exportDialog).length >= 2, 'Native spreadsheet/CSV export formats available');
        const compatible = exportDialog.querySelector('.o_import_compat input');
        if (compatible?.checked) compatible.click();
        await wait(() => exportDialog.querySelector(".o_export_tree_item[data-field_id='amount']"), 'native amount is exportable');
        const dialog = exportDialog.closest('.modal');
        (await wait(() => all('.o_form_button_cancel', dialog)[0], 'native export Close')).click();
        await wait(() => !all('.modal').length, 'export picker cancellation');
        const searchFacet = all('.o_searchview_facet').find((node) => node.textContent.includes('UI-NAV-ALPHA'));
        assert(searchFacet, 'Native search produces a removable facet');
        searchFacet.querySelector('.o_facet_remove').click();
        await wait(() => groups().length === 2, 'clearing memo filter restores both groups');
        await expandGroups();
        await wait(() => rows().length === 3, 'clearing filter restores the full batch');
        await backToForm('action_il_open_grouped_payments');
        console.log('HR navigation UI: flat batch tab, native two-group list, totals, filter/cancel, export picker and back passed');
    } else if (cfg.scenario === 'employee') {
        await wait(() => all("button[name='action_il_open_work_contact']")[0], 'employee form and Contact smart button');
        const more = all('.o_form_view .o_button_more')[0];
        if (more) {
            more.click();
            await wait(() => all('.o_dropdown_more')[0], 'native smart button overflow');
        }
        const buttons = all('.o-form-buttonbox button.oe_stat_button[name]');
        const names = buttons.map((button) => button.getAttribute('name'));
        assert(names[0] === 'action_il_open_work_contact' && names[1] === 'action_open_versions', 'Contact then History appear first');
        const ranks = {
            action_il_open_work_contact: 10, action_open_versions: 20,
            action_open_attendance_device_cards: 30, action_open_payslips: 40,
            [cfg.newPayslipAction]: 40, action_il_open_payments: 50,
            action_il_open_payroll_ledger: 60, action_open_documents: 70,
            action_open_work_entries: 90, action_open_last_month_attendances: 100,
        };
        const order = names.map((name) => ranks[name] || 85);
        assert(order.every((rank, index) => !index || rank >= order[index - 1]), `Smart button order: ${names.join(', ')}`);
        assert(names.includes('action_il_open_payments') && names.includes('action_il_open_payroll_ledger'), 'Payments and ledger are reachable through the native button box');
        assert(!names.includes('action_open_documents'), 'Zero Documents count hides its smart button');
        assert(!cfg.equipmentAction || !names.includes(cfg.equipmentAction), 'Zero Equipment count hides its smart button');
        assert(names.filter((name) => name === 'action_open_last_month_attendances').length <= 1, 'Permission variants do not duplicate Monthly Hours');
        const work = names.indexOf('action_open_work_entries');
        const hours = names.indexOf('action_open_last_month_attendances');
        assert(work >= 0 && hours > work && hours === names.length - 1, 'Work Entries precedes final Monthly Hours button');
        await clickName('action_il_open_payroll_ledger');
        await wait(() => rows().length === 1 && rowWith('UI-NAV-OPEN'), 'native ledger defaults to posted open entries');
        const residual = rowWith('UI-NAV-OPEN').querySelector("td[name='amount_residual']");
        assertMoneyCell(residual, -1200, 'Open ledger residual');
        assert(!rowWith('UI-NAV-OTHER-EMPLOYEE'), 'Ledger domain excludes another employee');
        const facets = all('.o_searchview_facet');
        for (const label of Object.values(cfg.filterLabels)) {
            assert(facets.some((facet) => facet.textContent.includes(label)), `Default native filter is visible: ${label}`);
        }
        const unreconciled = facets.find((facet) => facet.textContent.includes(cfg.filterLabels.unreconciled));
        unreconciled.querySelector('.o_facet_remove').click();
        await wait(() => rows().length === 3 && rowWith('UI-NAV-CLOSED'), 'removing Unreconciled restores settled ledger rows');
        assert(!rowWith('UI-NAV-DRAFT'), 'Posted filter still hides draft entries');
        const posted = all('.o_searchview_facet').find((facet) => facet.textContent.includes(cfg.filterLabels.posted));
        assert(posted, 'Posted remains independently removable');
        posted.querySelector('.o_facet_remove').click();
        await wait(() => rows().length === 4 && rowWith('UI-NAV-DRAFT'), 'removing Posted restores draft ledger rows');
        assert(!rowWith('UI-NAV-OTHER-EMPLOYEE'), 'Clearing native filters preserves employee/account/company domain');
        await backToForm('action_il_open_work_contact');
        await clickName('action_il_open_work_contact');
        await wait(() => all('.o_form_view')[0] && !all("button[name='action_il_open_work_contact']").length && all(".o_field_widget[name='name']").some((field) => field.textContent.includes(cfg.employeeName) || field.querySelector('input')?.value === cfg.employeeName), 'native contact form opens');
        console.log('HR navigation UI: smart button order, zero optional counts, native residuals and removable ledger filters passed');
    } else {
        throw new Error(`Unknown navigation scenario ${cfg.scenario}`);
    }
    console.log('test successful');
})().catch((error) => console.error(error.stack || String(error)));
