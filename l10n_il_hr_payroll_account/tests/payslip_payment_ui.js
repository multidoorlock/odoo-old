(async () => {
    const cfg = window.payrollSimulation;
    const visible = (node) => Boolean(node && node.getClientRects().length);
    const all = (selector, root = document) => [...root.querySelectorAll(selector)].filter(visible);
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    async function wait(check, message, timeout = 15000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
            const value = check();
            if (value) return value;
            await pause(80);
        }
        throw new Error(`UI timeout: ${message}\n${document.body.innerText.slice(-4500)}`);
    }
    const mainRows = () => all('.o_list_view .o_data_row').filter((row) => !row.closest('.modal'));
    const mainRow = (memo) => mainRows().find((row) => row.innerText.includes(memo));
    const dialogs = () => all('.modal');
    const dialog = () => dialogs().at(-1);
    const dialogRow = (memo) => all('.o_data_row', dialog()).find((row) => row.innerText.includes(memo));
    const number = (text) => Number(text.replace(/[^\d.\-]/g, ''));
    const cellAmount = (row, field) => number(row.querySelector(`[name='${field}']`).textContent);
    const topButton = (name) => all(`.o_action_manager button[name='${name}']`).find((node) => !node.closest('.modal'));
    async function clickButton(name) {
        (await wait(() => topButton(name), `button ${name}`)).click();
    }
    async function select(memos) {
        for (const row of mainRows()) {
            const checkbox = row.querySelector('.o_list_record_selector input');
            const wanted = memos.some((memo) => row.innerText.includes(memo));
            if (checkbox.checked !== wanted) checkbox.click();
        }
        await pause(120);
    }
    async function action(label) {
        (await wait(() => all(".o_cp_action_menus button[data-hotkey='u']")[0], 'Actions menu')).click();
        (await wait(() => all('.o_menu_item').find((item) => item.textContent.trim() === label), label)).click();
        await wait(() => dialog()?.querySelector("[name='source_payslip_id']"), 'selected payment dialog');
    }
    async function editAmount(memo, amount) {
        const row = await wait(() => dialogRow(memo), `dialog row ${memo}`);
        row.querySelector("[name='amount']").click();
        const input = await wait(() => row.querySelector("[name='amount'] input"), 'amount input');
        input.focus();
        input.value = String(amount);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.blur();
        await pause(180);
    }
    async function apply() {
        (await wait(() => all("button[name='action_apply']", dialog()).find((button) => !button.disabled), 'Apply')).click();
    }
    async function cancel() {
        (await wait(() => all("button[special='cancel']", dialog())[0], 'Cancel')).click();
        await wait(() => !dialogs().length, 'dialog cancellation');
    }
    async function dismissError(expected) {
        await wait(() => dialogs().length >= 2, 'native error dialog');
        assert(expected.test(dialog().innerText), `Unexpected validation message: ${dialog().innerText}`);
        const close = all('.modal-footer button', dialog()).find((button) => !button.disabled);
        assert(close, 'Validation dialog must be dismissible');
        close.click();
        await wait(() => dialogs().length === 1 && dialog().querySelector("[name='source_payslip_id']"),
                   'underlying amount form retained');
    }
    async function rpc(model, method, args, extraContext = {}) {
        const response = await fetch(`/web/dataset/call_kw/${model}/${method}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: Date.now(), params: {
                model, method, args, kwargs: { context: {
                    allowed_company_ids: [cfg.companyId], il_payslip_id: cfg.slipId, ...extraContext,
                } },
            } }),
        });
        const payload = await response.json();
        if (payload.error) throw new Error(JSON.stringify(payload.error));
        return payload.result;
    }
    async function candidateList() {
        await clickButton('action_il_add_payslip_payment');
        await wait(() => mainRow('UI-GAMMA') && topButton('action_il_select_payslip_payments') === undefined,
                   'candidate list without selected rows');
        assert(!mainRow('UI-EXHAUSTED'), 'Exhausted payment must not be selectable');
        const row = mainRow('UI-DELTA');
        assert(row && cellAmount(row, 'il_recognition_available_amount') === 600,
               'Partly used payment must expose its actual 600 residual');
        for (const name of ['date', 'partner_id', 'memo', 'amount', 'il_recognition_available_amount']) {
            assert(row.querySelector(`[name='${name}']`), `Candidate must show ${name}`);
        }
    }
    async function backToLinked() {
        window.history.back();
        await wait(() => mainRow('UI-ALPHA')?.querySelector("[name='il_payslip_linked_amount']"), 'back to linked payments');
    }

    await wait(() => mainRows().length === 2 && mainRow('UI-ALPHA'), 'initial linked list');
    assert(all("button[name='action_il_add_payslip_payment']").length === 1, 'Exactly one Add payment control');
    assert(!mainRows().some((row) => row.querySelector('button')), 'No per-row unlink control');
    const fields = [...mainRow('UI-ALPHA').querySelectorAll('td[name]')].map((node) => node.getAttribute('name'));
    assert(fields[fields.indexOf('amount') + 1] === 'il_payslip_linked_amount', 'Payment and recognition amounts are adjacent');
    assert(cellAmount(mainRow('UI-ALPHA'), 'amount') === 3000, 'Original amount visible');
    assert(cellAmount(mainRow('UI-ALPHA'), 'il_payslip_linked_amount') === 1000, 'Recognized amount visible');

    if (cfg.scenario === 'edit_recovery') {
        await select(['UI-ALPHA']);
        await action('שינוי סכום להכרה');
        await editAmount('UI-ALPHA', 500);
        await cancel();
        assert(cellAmount(mainRow('UI-ALPHA'), 'il_payslip_linked_amount') === 1000, 'Cancel must preserve link');

        await select(['UI-ALPHA']);
        await action('שינוי סכום להכרה');
        await editAmount('UI-ALPHA', 600);
        await apply();
        await wait(() => !dialogs().length && mainRow('UI-ALPHA') &&
            cellAmount(mainRow('UI-ALPHA'), 'il_payslip_linked_amount') === 600, 'saved amount and list return');

        await select(['UI-ALPHA']);
        await action('שינוי סכום להכרה');
        await editAmount('UI-ALPHA', 3001);
        await apply();
        await dismissError(/סכום|יתרה|balance|amount/i);
        const retained = dialogRow('UI-ALPHA').querySelector("[name='amount'] input");
        assert(retained ? number(retained.value) === 3001 : cellAmount(dialogRow('UI-ALPHA'), 'amount') === 3001,
               'Residual cap error must retain proposed amount');
        await cancel();

        await select(['UI-ALPHA']);
        await action('שינוי סכום להכרה');
        await editAmount('UI-ALPHA', 550);
        const [current] = await rpc('account.payment', 'read', [[cfg.alphaId], ['il_payslip_link_snapshot']]);
        await rpc('account.payment', 'write', [[cfg.alphaId], {
            il_payslip_linked_amount: 650, il_payslip_link_write_token: current.il_payslip_link_snapshot,
        }]);
        await apply();
        await dismissError(/השתנ|רענן|changed|refresh/i);
        const [fresh] = await rpc('account.payment', 'read', [[cfg.alphaId], ['il_payslip_linked_amount']]);
        assert(fresh.il_payslip_linked_amount === 650, 'Stale form must not overwrite a newer link');
        await cancel();
        console.log('Payroll UI: cancel, save/list return, residual error and stale-form recovery passed');
    } else if (cfg.scenario === 'multi_add_remove') {
        await candidateList();
        assert(!mainRow('UI-ALPHA') && !mainRow('UI-BETA'), 'Current links excluded from candidates');
        await backToLinked();
        await select(['UI-ALPHA', 'UI-BETA']);
        await action('הסרת קישור מהתלוש');
        assert(all('.o_data_row', dialog()).length === 2, 'Both selected links are reviewed');
        assert(!dialog().querySelector("[name='amount'] input"), 'Removal review is read-only');
        await cancel();
        assert(mainRows().length === 2, 'Cancel removal preserves both rows');
        await select(['UI-ALPHA', 'UI-BETA']);
        await action('הסרת קישור מהתלוש');
        await apply();
        await wait(() => !dialogs().length && mainRows().length === 0 && topButton('action_il_add_payslip_payment'),
                   'both links removed and Add remains available');
        await candidateList();
        assert(cellAmount(mainRow('UI-ALPHA'), 'il_recognition_available_amount') === 3000,
               'Removing a link releases its recognition balance');
        await select(['UI-ALPHA', 'UI-BETA']);
        await clickButton('action_il_select_payslip_payments');
        await wait(() => dialog()?.querySelector("[name='source_payslip_id']"), 'selected candidates review');
        assert(all('.o_data_row', dialog()).length === 2, 'Review includes exactly selected payments');
        await editAmount('UI-ALPHA', 1000);
        await editAmount('UI-BETA', 200);
        await apply();
        await wait(() => !dialogs().length && mainRows().length === 2 &&
            mainRow('UI-ALPHA')?.querySelector("[name='il_payslip_linked_amount']"), 'relinked payment list');
        assert(cellAmount(mainRow('UI-ALPHA'), 'il_payslip_linked_amount') === 1000, 'Alpha restored');
        assert(cellAmount(mainRow('UI-BETA'), 'il_payslip_linked_amount') === 200, 'Beta restored');
        console.log('Payroll UI: native candidate details, back, multiselect remove/cancel and add/save passed');
    } else if (cfg.scenario === 'filter_export_back') {
        const search = await wait(() => all('.o_searchview_input')[0], 'native search input');
        search.focus();
        search.value = 'UI-ALPHA';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        await wait(() => all('.o_searchview_autocomplete')[0], 'native search suggestions');
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }));
        await wait(() => mainRows().length === 1 && mainRow('UI-ALPHA'), 'memo filter');
        await select(['UI-ALPHA']);
        (await wait(() => all(".o_cp_action_menus button[data-hotkey='u']")[0], 'Actions')).click();
        (await wait(() => all('.o_menu_item').find((item) => /^(Export|ייצוא|יצוא)$/.test(item.textContent.trim())), 'native Export action')).click();
        await wait(() => all('.o_export_data_dialog')[0], 'native Export dialog');
        const compatibility = dialog().querySelector('.o_import_compat input');
        if (compatibility?.checked) compatibility.click();
        for (const name of ['amount', 'il_payslip_linked_amount']) {
            if (!dialog().querySelector(`.o_export_field[data-field_id='${name}']`)) {
                (await wait(() => dialog().querySelector(`.o_export_tree_item[data-field_id='${name}'] .o_add_field`), `export ${name}`)).click();
            }
        }
        assert(dialog().querySelector(".o_export_field[data-field_id='il_payslip_linked_amount']"), 'Recognition amount exportable');
        let downloaded = false;
        const realFetch = window.fetch;
        window.fetch = async function (...args) {
            const response = await realFetch.apply(this, args);
            if (String(args[0]).includes('/web/export/') && response.ok) {
                const bytes = await response.clone().arrayBuffer();
                if (bytes.byteLength > 50) downloaded = true;
            }
            return response;
        };
        const realOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function (method, url, ...args) {
            if (String(url).includes('/web/export/')) this.addEventListener('load', () => {
                if (this.status === 200 && this.response &&
                    (this.response.size || this.response.byteLength || this.response.length) > 50) downloaded = true;
            });
            return realOpen.call(this, method, url, ...args);
        };
        try {
            dialog().querySelector('button.o_select_button').click();
            await wait(() => downloaded, 'real export response bytes', 25000);
        } finally {
            window.fetch = realFetch;
            XMLHttpRequest.prototype.open = realOpen;
        }
        if (dialogs().length) all('.o_form_button_cancel', dialog())[0]?.click();
        await wait(() => !dialogs().length, 'export dialog closes');
        const removeFacet = await wait(() => all('.o_facet_remove')[0], 'clear search facet');
        removeFacet.click();
        await wait(() => mainRows().length === 2, 'unfiltered linked list');
        await select([]);
        await candidateList();
        await backToLinked();
        console.log('Payroll UI: native filtering, amount export/download and back navigation passed');
    } else {
        throw new Error(`Unknown simulation ${cfg.scenario}`);
    }
    console.log('test successful');
})().catch((error) => console.error(error.stack || String(error)));
