import { titleService } from "@web/core/browser/title_service";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";

async function updateCompanyFavicon() {
    const company = user.activeCompany;
    const favicon = document.querySelector("link[rel~='icon']");

    if (!company || !favicon) {
        return;
    }

    const logo = new Image();
    logo.src = `/web/image/res.company/${company.id}/logo?unique=${Date.now()}`;
    await logo.decode();

    const size = 32;
    const scale = Math.min(size / logo.naturalWidth, size / logo.naturalHeight);
    const width = logo.naturalWidth * scale;
    const height = logo.naturalHeight * scale;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;

    const context = canvas.getContext("2d");
    context.clearRect(0, 0, size, size);
    context.drawImage(logo, (size - width) / 2, (size - height) / 2, width, height);

    favicon.type = "image/png";
    favicon.href = canvas.toDataURL("image/png");
}

patch(titleService, {
    start() {
        const service = super.start(...arguments);
        const originalSetParts = service.setParts;

        service.setParts = () => {
            originalSetParts({
                action: false,
                brand: user.activeCompany?.name || "Odoo",
            });
        };

        service.setParts();
        updateCompanyFavicon().catch(() => {});

        return service;
    },
});
