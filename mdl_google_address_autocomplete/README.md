# Multi Doorlock - Hebrew Address Autocomplete

Odoo 19 addon that requests Hebrew (`language=iw`) from Google Places for both
address suggestions and the details of the selected address. It extends the
standard controller; no Odoo core files are modified.

## Scope

- Hebrew is requested for every call through the extended controller, regardless
  of the Odoo interface, contact, or explicitly supplied language.
- API keys, session tokens, optional country filters, address parsing, routes,
  access checks, and upstream error handling remain unchanged.
- No Israel-only country filter is added. Google may use a fallback where a
  Hebrew name is unavailable.
- Existing saved addresses and contact-language preferences are not rewritten.
- This does not change the Google attribution or fix its separate spacing issue.

## Deployment

Test in an Odoo.sh development/staging database before production deployment.
The addon depends on `google_address_autocomplete` and is eligible for automatic
installation when that dependency is installed. After deploying the code and
refreshing the Apps list, verify this addon is installed; install it explicitly
if necessary. No additional Google key or system parameter is needed.

Test with the existing Google configuration by typing a full Israeli street,
house number, and city in Contacts, selecting a suggestion, and checking the
filled street and city. Test an English-interface user as well. Google can
return mixed-language results where translated place names are unavailable.

## Tests

The module includes isolated controller-delegation tests, with the upstream
methods mocked to avoid Google requests and billable API usage. In an Odoo test
database, run:

```sh
odoo-bin -d TEST_DATABASE -i mdl_google_address_autocomplete \
  --test-enable --test-tags /mdl_google_address_autocomplete --stop-after-init
```

Uninstall this addon to restore the standard language behavior. Do not uninstall
`google_address_autocomplete` for rollback.

## References

- Odoo 19 controller:
  https://github.com/odoo/odoo/blob/19.0/addons/google_address_autocomplete/controllers/google_address_autocomplete.py
- Google's supported language codes:
  https://developers.google.com/maps/faq#languagesupport
