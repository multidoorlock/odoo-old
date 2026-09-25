import base64

from odoo import Command, api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import file_open


MARITAL_SELECTION = [
    ('single', 'רווק/ה'),
    ('married', 'נשוי/אה'),
    ('divorced', 'גרוש/ה'),
    ('widower', 'אלמן/ה'),
    ('separated', 'פרוד/ה'),
]

INCOME_TYPE_SELECTION = [
    ('monthly', 'משכורת חודש'),
    ('additional', 'משכורת בעד משרה נוספת'),
    ('partial', 'משכורת חלקית'),
    ('daily', 'שכר עבודה (עובד יומי)'),
    ('pension', 'קצבה'),
    ('scholarship', 'מלגה'),
]

TAX_YEAR_SELECTION = [(str(year), str(year)) for year in range(1900, 2201)]

_SIGN_CHILD_ROW_COUNT = 13


_SIGN_CHECK_FIELDS = (
    'sign_sex_male', 'sign_sex_female',
    'sign_marital_single', 'sign_marital_married', 'sign_marital_divorced',
    'sign_marital_widower', 'sign_marital_separated',
    'sign_resident_yes', 'sign_resident_no',
    'sign_kibbutz_yes', 'sign_kibbutz_no',
    'sign_kibbutz_not_transferred',
    'sign_health_fund_yes', 'sign_health_fund_no',
    'sign_income_monthly', 'sign_income_additional', 'sign_income_partial',
    'sign_income_daily', 'sign_income_pension', 'sign_income_scholarship',
    'sign_other_income_no', 'sign_other_income_yes',
    'sign_other_income_monthly', 'sign_other_income_additional',
    'sign_other_income_partial', 'sign_other_income_daily',
    'sign_other_income_pension', 'sign_other_income_scholarship',
    'sign_credit_points_here', 'sign_credit_points_elsewhere',
    'sign_no_study_fund_elsewhere', 'sign_no_pension_elsewhere',
    'sign_spouse_no_income', 'sign_spouse_has_income_yes',
    'sign_spouse_income_work', 'sign_spouse_income_other',
    'sign_relief_resident', 'sign_relief_disabled_blind',
    'sign_relief_disabled_benefit', 'sign_relief_eligible_settlement',
    'sign_relief_new_immigrant', 'sign_relief_spouse_no_income',
    'sign_relief_single_parent_family', 'sign_relief_children_in_custody',
    'sign_relief_other_children', 'sign_relief_single_parent',
    'sign_relief_support_non_custody', 'sign_relief_disabled_children',
    'sign_relief_alimony_former_spouse', 'sign_relief_age_16_18',
    'sign_relief_discharged_service', 'sign_relief_studies',
    'sign_relief_reserve_combat', 'sign_tax_no_income',
    'sign_tax_additional_income', 'sign_tax_officer',
)

_SIGN_AUTOFILL_FIELDS = (
    'sign_full_address', 'sign_identity_number',
    *_SIGN_CHECK_FIELDS,
    *(f'sign_child_{index}_{suffix}' for index in range(1, _SIGN_CHILD_ROW_COUNT + 1)
      for suffix in ('name', 'identification_id', 'birthday', 'custody', 'allowance')),
    *(f'sign_other_employer_{index}_{suffix}' for index in range(1, 4)
      for suffix in ('name', 'address', 'withholding_file', 'income_type',
                     'monthly_income', 'tax_withheld')),
)


def _sign_item(key, label, auto_field, page, left, top, width, height=4.455,
               item_type='text', type_xmlid='sign.sign_item_type_text'):
    return {
        'key': key,
        'label': label,
        'auto_field': auto_field,
        'page': page,
        'left': left,
        'top': top,
        'width': width,
        'height': height,
        'item_type': item_type,
        'type_xmlid': type_xmlid,
    }


def _sign_check(key, label, auto_field, page, left, top):
    """Place a small tick exactly over a checkbox on the A4 source form."""
    return _sign_item(
        key, label, auto_field, page, left, top, 3.2, 3.2,
        item_type='checkbox', type_xmlid='sign.sign_item_type_checkbox',
    )


_SIGN_TEMPLATE_ITEMS = [
    _sign_item('tax_year', 'שנת מס', 'tax_year', 1, 76.5, 29.9, 36.5, 6),
    _sign_item('employer_name', 'שם המעסיק', 'employer_name', 1, 146, 61.0, 39),
    _sign_item('employer_address', 'כתובת המעסיק', 'employer_address', 1, 75, 61.0, 69),
    _sign_item('employer_phone', 'טלפון המעסיק', 'employer_phone', 1, 46, 61.0, 27),
    _sign_item('employer_withholding_file', 'תיק ניכויים', 'employer_withholding_file', 1, 10, 61.0, 34),
    _sign_item('identification_id', 'מספר זהות', 'identification_id', 1, 155, 79.0, 31),
    _sign_item('last_name', 'שם משפחה', 'last_name', 1, 111, 79.0, 42),
    _sign_item('first_name', 'שם פרטי', 'first_name', 1, 76, 79.0, 33),
    _sign_item('birthday', 'תאריך לידה', 'birthday', 1, 44, 79.0, 30),
    _sign_item('immigration_date', 'תאריך עלייה', 'immigration_date', 1, 11, 79.0, 31),
    _sign_item('passport_id', 'מספר דרכון', 'passport_id', 1, 140, 89.5, 49),
    _sign_item('full_address', 'כתובת העובד', 'sign_full_address', 1, 10.5, 89.5, 128),
    _sign_item('private_email', 'דואר אלקטרוני', 'private_email', 1, 127.5, 111.0, 62),
    _sign_item('private_phone', 'טלפון', 'private_phone', 1, 72.5, 111.0, 53),
    _sign_item('mobile_phone', 'טלפון נייד', 'mobile_phone', 1, 39.0, 111.0, 31.5),
    _sign_check('sex_male', 'זכר', 'sign_sex_male', 1, 186.0, 97.7),
    _sign_check('sex_female', 'נקבה', 'sign_sex_female', 1, 186.0, 102.3),
    _sign_check('marital_single', 'רווק', 'sign_marital_single', 1, 172.2, 97.3),
    _sign_check('marital_married', 'נשוי', 'sign_marital_married', 1, 151.4, 97.3),
    _sign_check('marital_divorced', 'גרוש', 'sign_marital_divorced', 1, 127.6, 97.3),
    _sign_check('marital_widower', 'אלמן', 'sign_marital_widower', 1, 155.7, 101.9),
    _sign_check('marital_separated', 'פרוד', 'sign_marital_separated', 1, 172.2, 101.9),
    _sign_check('resident_yes', 'תושב ישראל - כן', 'sign_resident_yes', 1, 108.9, 97.6),
    _sign_check('resident_no', 'תושב ישראל - לא', 'sign_resident_no', 1, 108.9, 102.2),
    _sign_check('kibbutz_yes', 'חבר קיבוץ - הכנסה מועברת', 'sign_kibbutz_yes', 1, 87.4, 97.6),
    _sign_check('kibbutz_no', 'חבר קיבוץ - לא', 'sign_kibbutz_no', 1, 95.1, 97.6),
    _sign_check('kibbutz_not_transferred', 'חבר קיבוץ - הכנסה אינה מועברת', 'sign_kibbutz_not_transferred', 1, 95.1, 102.2),
    _sign_check('health_fund_no', 'חבר קופת חולים - לא', 'sign_health_fund_no', 1, 43.1, 97.3),
    _sign_check('health_fund_yes', 'חבר קופת חולים - כן', 'sign_health_fund_yes', 1, 43.1, 101.9),
    _sign_item('health_fund_name', 'שם קופת חולים', 'health_fund_name', 1, 10.5, 108.0, 27.5),
    _sign_item('employment_start_date', 'תחילת עבודה', 'employment_start_date', 1, 12, 136.5, 31),
    _sign_check('income_monthly', 'משכורת חודש', 'sign_income_monthly', 1, 83.7, 125.6),
    _sign_check('income_additional', 'משרה נוספת', 'sign_income_additional', 1, 83.7, 129.8),
    _sign_check('income_partial', 'משכורת חלקית', 'sign_income_partial', 1, 83.7, 134.1),
    _sign_check('income_daily', 'שכר עבודה', 'sign_income_daily', 1, 83.7, 138.3),
    _sign_check('income_pension', 'קצבה', 'sign_income_pension', 1, 83.7, 142.5),
    _sign_check('income_scholarship', 'מלגה', 'sign_income_scholarship', 1, 83.7, 146.8),
    _sign_check('other_income_no', 'אין הכנסות אחרות', 'sign_other_income_no', 1, 83.0, 159.7),
    _sign_check('other_income_yes', 'יש הכנסות אחרות', 'sign_other_income_yes', 1, 83.0, 168.4),
    _sign_check('other_income_monthly', 'הכנסה אחרת חודשית', 'sign_other_income_monthly', 1, 83.0, 172.5),
    _sign_check('other_income_additional', 'הכנסה אחרת נוספת', 'sign_other_income_additional', 1, 83.0, 176.4),
    _sign_check('other_income_partial', 'הכנסה אחרת חלקית', 'sign_other_income_partial', 1, 83.0, 180.3),
    _sign_check('other_income_daily', 'הכנסה אחרת יומית', 'sign_other_income_daily', 1, 41.4, 172.5),
    _sign_check('other_income_pension', 'קצבה ממקור אחר', 'sign_other_income_pension', 1, 41.4, 176.4),
    _sign_check('other_income_scholarship', 'מלגה ממקור אחר', 'sign_other_income_scholarship', 1, 41.4, 180.3),
    _sign_item('other_income_other_details', 'פירוט הכנסה אחרת', 'other_income_other_details', 1, 10.5, 184.0, 48, 4),
    _sign_check('credit_points_here', 'נקודות זיכוי בהכנסה זו', 'sign_credit_points_here', 1, 82.8, 188.6),
    _sign_check('credit_points_elsewhere', 'נקודות זיכוי בהכנסה אחרת', 'sign_credit_points_elsewhere', 1, 82.8, 196.9),
    _sign_check('no_study_fund_elsewhere', 'אין קרן השתלמות בהכנסה אחרת', 'sign_no_study_fund_elsewhere', 1, 82.8, 205.4),
    _sign_check('no_pension_elsewhere', 'אין פנסיה בהכנסה אחרת', 'sign_no_pension_elsewhere', 1, 82.8, 217.5),
    _sign_item('spouse_identification_id', 'מספר זהות בן זוג', 'spouse_identification_id', 1, 154, 244.5, 35),
    _sign_item('spouse_last_name', 'שם משפחה בן זוג', 'spouse_last_name', 1, 111, 244.5, 41),
    _sign_item('spouse_first_name', 'שם פרטי בן זוג', 'spouse_first_name', 1, 76, 244.5, 33),
    _sign_item('spouse_birthdate', 'תאריך לידת בן זוג', 'spouse_birthdate', 1, 44, 244.5, 30),
    _sign_item('spouse_immigration_date', 'תאריך עליית בן זוג', 'spouse_immigration_date', 1, 11, 244.5, 31),
    _sign_item('spouse_passport_id', 'דרכון בן זוג', 'spouse_passport_id', 1, 149, 254.0, 40),
    _sign_check('spouse_no_income', 'בן זוג ללא הכנסה', 'sign_spouse_no_income', 1, 144.48, 253.64),
    _sign_check('spouse_has_income_yes', 'לבן זוג יש הכנסה', 'sign_spouse_has_income_yes', 1, 99.54, 253.64),
    _sign_check('spouse_income_work', 'הכנסת בן זוג מעבודה', 'sign_spouse_income_work', 1, 56.49, 253.64),
    _sign_check('spouse_income_other', 'הכנסה אחרת של בן זוג', 'sign_spouse_income_other', 1, 28.56, 253.64),
    _sign_item('identity_number_page_2', 'מספר זהות - עמוד 2', 'sign_identity_number', 2, 30, 4.2, 30),
    _sign_check('relief_resident', 'זיכוי תושב', 'sign_relief_resident', 2, 180.0, 13.6),
    _sign_check('relief_disabled_blind', 'נכה או עיוור', 'sign_relief_disabled_blind', 2, 180.0, 19.0),
    _sign_check('relief_disabled_benefit', 'תגמול נכים', 'sign_relief_disabled_benefit', 2, 180.0, 26.9),
    _sign_check('relief_eligible_settlement', 'יישוב מזכה', 'sign_relief_eligible_settlement', 2, 180.0, 33.2),
    _sign_item('eligible_settlement_name', 'שם יישוב מזכה', 'eligible_settlement_name', 2, 99, 37.4, 55),
    _sign_item('eligible_settlement_from', 'מגורים ביישוב מתאריך', 'eligible_settlement_from', 2, 89, 32.7, 27),
    _sign_check('relief_new_immigrant', 'עולה חדש', 'sign_relief_new_immigrant', 2, 180.0, 42.6),
    _sign_item('new_immigrant_from', 'עלייה מתאריך', 'new_immigrant_from', 2, 124, 45.8, 32),
    _sign_item('no_income_until_date', 'ללא הכנסה עד', 'no_income_until_date', 2, 60, 50.5, 25),
    _sign_check('relief_spouse_no_income', 'בן זוג ללא הכנסה', 'sign_relief_spouse_no_income', 2, 180.0, 56.5),
    _sign_check('relief_single_parent_family', 'משפחה חד הורית', 'sign_relief_single_parent_family', 2, 180.0, 64.4),
    _sign_check('relief_children_in_custody', 'ילדים בחזקה', 'sign_relief_children_in_custody', 2, 180.0, 72.7),
    _sign_item('custody_children_born', 'ילדים שנולדו השנה', 'custody_children_born', 2, 127, 80.4, 10, 3.5),
    _sign_item('custody_children_age_1_2', 'ילדים גיל 1-2', 'custody_children_age_1_2', 2, 96, 84.7, 10, 3.5),
    _sign_item('custody_children_age_3', 'ילדים גיל 3', 'custody_children_age_3', 2, 112, 88.7, 10, 3.5),
    _sign_item('custody_children_age_4_5', 'ילדים גיל 4-5', 'custody_children_age_4_5', 2, 13, 80.8, 10, 3.5),
    _sign_item('custody_children_age_6_17', 'ילדים גיל 6-17', 'custody_children_age_6_17', 2, 12, 84.7, 10, 3.5),
    _sign_item('custody_children_age_18', 'ילדים גיל 18', 'custody_children_age_18', 2, 25, 88.7, 10, 3.5),
    _sign_check('relief_other_children', 'ילדים אחרים', 'sign_relief_other_children', 2, 180.0, 93.3),
    _sign_item('other_children_born', 'ילדים אחרים שנולדו השנה', 'other_children_born', 2, 127, 97.3, 10, 3.5),
    _sign_item('other_children_age_1_2', 'ילדים אחרים גיל 1-2', 'other_children_age_1_2', 2, 96, 101.5, 10, 3.5),
    _sign_item('other_children_age_3', 'ילדים אחרים גיל 3', 'other_children_age_3', 2, 112, 105.5, 10, 3.5),
    _sign_item('other_children_age_4_5', 'ילדים אחרים גיל 4-5', 'other_children_age_4_5', 2, 13, 97.9, 10, 3.5),
    _sign_item('other_children_age_6_17', 'ילדים אחרים גיל 6-17', 'other_children_age_6_17', 2, 12, 101.5, 10, 3.5),
    _sign_check('relief_single_parent', 'הורה יחיד', 'sign_relief_single_parent', 2, 180.0, 110.8),
    _sign_check('relief_support_non_custody', 'כלכלת ילדים שאינם בחזקה', 'sign_relief_support_non_custody', 2, 180.0, 117.2),
    _sign_check('relief_disabled_children', 'ילדים עם מוגבלות', 'sign_relief_disabled_children', 2, 180.0, 125.9),
    _sign_item('disabled_children_count', 'מספר ילדים עם מוגבלות', 'disabled_children_count', 2, 118, 128.4, 12, 3.5),
    _sign_check('relief_alimony_former_spouse', 'מזונות לבן זוג לשעבר', 'sign_relief_alimony_former_spouse', 2, 180.0, 134.0),
    _sign_check('relief_age_16_18', 'גיל 16-18', 'sign_relief_age_16_18', 2, 180.0, 139.8),
    _sign_check('relief_discharged_service', 'חייל משוחרר', 'sign_relief_discharged_service', 2, 180.0, 145.4),
    _sign_item('service_start_date', 'תחילת שירות', 'service_start_date', 2, 73, 148.2, 27, 3.8),
    _sign_item('service_end_date', 'סיום שירות', 'service_end_date', 2, 18, 148.2, 27, 3.8),
    _sign_check('relief_studies', 'זיכוי לימודים', 'sign_relief_studies', 2, 180.0, 153.6),
    _sign_check('relief_reserve_combat', 'מילואים כלוחם', 'sign_relief_reserve_combat', 2, 180.0, 158.3),
    _sign_item('reserve_combat_days', 'ימי מילואים כלוחם', 'reserve_combat_days', 2, 46, 157.8, 10, 3.5),
    _sign_check('tax_no_income', 'תיאום מס - ללא הכנסה', 'sign_tax_no_income', 2, 180.5, 168.8),
    _sign_check('tax_additional_income', 'תיאום מס - הכנסה נוספת', 'sign_tax_additional_income', 2, 180.5, 179.1),
    _sign_check('tax_officer', 'תיאום מס פקיד שומה', 'sign_tax_officer', 2, 180.5, 207.5),
    _sign_item('declaration_date', 'תאריך הצהרה', 'declaration_date', 2, 49, 229.5, 23, 4),
]

for _child_index in range(1, _SIGN_CHILD_ROW_COUNT + 1):
    _child_top = 141.0 + (_child_index - 1) * 9.25
    _SIGN_TEMPLATE_ITEMS.extend([
        _sign_item(f'child_{_child_index}_name', f'ילד {_child_index} - שם', f'sign_child_{_child_index}_name', 1, 151, _child_top, 30),
        _sign_item(f'child_{_child_index}_id', f'ילד {_child_index} - זהות', f'sign_child_{_child_index}_identification_id', 1, 121, _child_top, 28),
        _sign_item(f'child_{_child_index}_birthday', f'ילד {_child_index} - לידה', f'sign_child_{_child_index}_birthday', 1, 88, _child_top, 30),
        _sign_check(f'child_{_child_index}_custody', f'ילד {_child_index} - בחזקה', f'sign_child_{_child_index}_custody', 1, 183.8, _child_top),
        _sign_check(f'child_{_child_index}_allowance', f'ילד {_child_index} - קצבה', f'sign_child_{_child_index}_allowance', 1, 187.4, _child_top),
    ])

for _employer_index in range(1, 4):
    _employer_top = 192.5 + (_employer_index - 1) * 4.9
    _SIGN_TEMPLATE_ITEMS.extend([
        _sign_item(f'other_employer_{_employer_index}_name', f'מעסיק נוסף {_employer_index} - שם', f'sign_other_employer_{_employer_index}_name', 2, 158.5, _employer_top, 30.5),
        _sign_item(f'other_employer_{_employer_index}_address', f'מעסיק נוסף {_employer_index} - כתובת', f'sign_other_employer_{_employer_index}_address', 2, 111.0, _employer_top, 45.5),
        _sign_item(f'other_employer_{_employer_index}_file', f'מעסיק נוסף {_employer_index} - תיק', f'sign_other_employer_{_employer_index}_withholding_file', 2, 81.0, _employer_top, 28.0),
        _sign_item(f'other_employer_{_employer_index}_type', f'מעסיק נוסף {_employer_index} - סוג', f'sign_other_employer_{_employer_index}_income_type', 2, 62.0, _employer_top, 17.0),
        _sign_item(f'other_employer_{_employer_index}_income', f'מעסיק נוסף {_employer_index} - הכנסה', f'sign_other_employer_{_employer_index}_monthly_income', 2, 36.5, _employer_top, 23.5),
        _sign_item(f'other_employer_{_employer_index}_tax', f'מעסיק נוסף {_employer_index} - מס', f'sign_other_employer_{_employer_index}_tax_withheld', 2, 11.0, _employer_top, 23.5),
    ])


# The active template created in Sign is the visual reference for the legal
# form.  These anchors are the exact millimetre values measured from that
# template.  Keep them here (instead of relying on editor-generated IDs) so
# the same layout is reproducible on every database.
_SIGN_MANUAL_LAYOUT = {
    'tax_year': (1, 76.50, 29.997, 23.50, 4.455),
    'employer_withholding_file': (1, 13.86, 58.806, 30.24, 4.455),
    'employer_phone': (1, 47.25, 58.806, 25.41, 4.455),
    'employer_address': (1, 75.18, 58.806, 69.93, 4.455),
    'employer_name': (1, 148.05, 58.806, 40.95, 4.455),
    'immigration_date': (1, 11.34, 78.111, 29.40, 4.455),
    'birthday': (1, 43.05, 78.111, 29.40, 4.455),
    'first_name': (1, 75.60, 78.111, 33.18, 4.455),
    'last_name': (1, 112.98, 78.111, 39.69, 4.455),
    'identification_id': (1, 156.03, 78.111, 33.60, 4.455),
    'private_zip': (1, 10.50, 86.427, 27.72, 4.455),
    'private_city': (1, 38.22, 86.427, 32.97, 4.455),
    'private_house_number': (1, 70.98, 86.427, 9.87, 4.455),
    'private_street': (1, 80.85, 86.427, 57.54, 4.455),
    'passport_id': (1, 139.44, 87.912, 49.98, 4.455),
    # The fund name belongs on the second health-fund line, not in the phone
    # row below it.  This also leaves exactly the two legal phone fields.
    'health_fund_name': (1, 10.50, 103.00, 27.60, 3.55),
    # Keep the two phone boxes exactly as positioned in the approved active
    # template.  There must not be a third field on this row.
    'mobile_phone': (1, 26.67, 111.67, 44.73, 3.56),
    'private_phone': (1, 85.68, 111.08, 41.16, 3.56),
    'private_email': (1, 127.68, 111.55, 62.45, 3.55),
    'employment_start_date': (1, 11.20, 133.25, 31.20, 4.45),
    'eligible_settlement_from': (2, 89.00, 33.15, 27.00, 3.20),
    'eligible_settlement_name': (2, 103.83, 38.39, 51.50, 3.75),
    'new_immigrant_from': (2, 116.44, 43.43, 27.36, 3.75),
    'no_income_until_date': (2, 67.37, 48.35, 21.03, 3.75),
    'disabled_children_count': (2, 157.98, 126.02, 6.84, 3.45),
    'custody_children_born': (2, 130.03, 81.30, 8.11, 3.70),
    'custody_children_age_1_2': (2, 98.72, 85.47, 8.12, 3.70),
    'custody_children_age_3': (2, 114.34, 89.24, 8.11, 3.70),
    'custody_children_age_4_5': (2, 15.37, 81.66, 8.27, 3.70),
    'custody_children_age_6_17': (2, 13.95, 85.18, 8.28, 3.70),
    'custody_children_age_18': (2, 27.59, 89.24, 8.12, 3.70),
    'other_children_born': (2, 130.03, 98.06, 8.11, 3.70),
    'other_children_age_1_2': (2, 98.72, 102.23, 8.12, 3.70),
    'other_children_age_3': (2, 114.34, 106.00, 8.11, 3.70),
    'other_children_age_4_5': (2, 15.37, 98.42, 8.27, 3.70),
    'other_children_age_6_17': (2, 13.95, 101.94, 8.28, 3.70),
    'service_start_date': (2, 67.96, 145.46, 20.19, 3.75),
    'service_end_date': (2, 20.75, 145.82, 21.18, 3.75),
    'reserve_combat_days': (2, 120.25, 158.45, 8.20, 4.10),
    'declaration_date': (2, 49.34, 227.22, 31.08, 4.15),
}

# Exact cell interiors measured from the legal source PDF.  The child table
# has thirteen rows and uses a 7.72 mm row pitch; the additional-employer
# table uses 5.01 mm.  The former ten-row layer skipped the first legal row
# and left the final two rows empty.
for _child_index in range(1, _SIGN_CHILD_ROW_COUNT + 1):
    _child_top = 134.53 + (_child_index - 1) * 7.72
    _SIGN_MANUAL_LAYOUT.update({
        f'child_{_child_index}_name': (1, 158.70, _child_top, 24.42, 4.60),
        f'child_{_child_index}_id': (1, 122.72, _child_top, 35.25, 4.60),
        f'child_{_child_index}_birthday': (1, 90.50, _child_top, 31.52, 4.60),
        f'child_{_child_index}_custody': (1, 183.50, _child_top + 0.70, 3.20, 3.20),
        f'child_{_child_index}_allowance': (1, 187.10, _child_top + 0.70, 3.20, 3.20),
    })

for _employer_index in range(1, 4):
    _employer_top = 192.90 + (_employer_index - 1) * 5.01
    _SIGN_MANUAL_LAYOUT.update({
        f'other_employer_{_employer_index}_name': (2, 157.05, _employer_top, 32.45, 4.55),
        f'other_employer_{_employer_index}_address': (2, 109.60, _employer_top, 46.95, 4.55),
        f'other_employer_{_employer_index}_file': (2, 81.90, _employer_top, 27.20, 4.55),
        f'other_employer_{_employer_index}_type': (2, 61.30, _employer_top, 20.10, 4.55),
        f'other_employer_{_employer_index}_income': (2, 35.70, _employer_top, 25.10, 4.55),
        f'other_employer_{_employer_index}_tax': (2, 10.40, _employer_top, 24.80, 4.55),
    })

# A legal address is four distinct boxes on the source PDF.  The former
# combined address overlay crossed column borders and made the result hard to
# read, so it is deliberately replaced with one native text item per box.
_SIGN_TEMPLATE_ITEMS[:] = [
    definition for definition in _SIGN_TEMPLATE_ITEMS
    if definition['key'] not in {'full_address', 'other_income_other_details'}
]
_SIGN_TEMPLATE_ITEMS.extend([
    _sign_item('private_street', 'רחוב / שכונה', 'private_street',
               1, 80.85, 86.427, 57.54),
    _sign_item('private_house_number', 'מספר בית', 'private_house_number',
               1, 70.98, 86.427, 9.87),
    _sign_item('private_city', 'עיר / יישוב', 'private_city',
               1, 38.22, 86.427, 32.97),
    _sign_item('private_zip', 'מיקוד', 'private_zip',
               1, 10.50, 86.427, 27.72),
])

_SIGN_MANUAL_LAYOUT.update({
    # Spouse-income boxes sit on one baseline at the bottom of page 1.
    'spouse_no_income': (1, 144.48, 253.64, 3.20, 3.20),
    'spouse_has_income_yes': (1, 99.54, 253.64, 3.20, 3.20),
    'spouse_income_work': (1, 56.49, 253.64, 3.20, 3.20),
    'spouse_income_other': (1, 28.56, 253.64, 3.20, 3.20),
    # The page-two identity line begins after the printed page caption.
    'identity_number_page_2': (2, 33.39, 4.16, 27.30, 4.75),
})

# The relief checkboxes form a single printed column on page 2.  Their source
# boxes share the same X coordinate and are about 1.5 mm below the old layer.
for _key, _top in {
    'relief_resident': 15.17,
    'relief_disabled_blind': 20.46,
    'relief_disabled_benefit': 28.39,
    'relief_eligible_settlement': 34.75,
    'relief_new_immigrant': 44.12,
    'relief_spouse_no_income': 58.05,
    'relief_single_parent_family': 65.96,
    'relief_children_in_custody': 74.25,
    'relief_other_children': 94.91,
    'relief_single_parent': 112.32,
    'relief_support_non_custody': 118.66,
    'relief_disabled_children': 127.60,
    'relief_alimony_former_spouse': 135.50,
    'relief_age_16_18': 141.20,
    'relief_discharged_service': 146.60,
    'relief_studies': 155.00,
    'relief_reserve_combat': 159.80,
}.items():
    _SIGN_MANUAL_LAYOUT[_key] = (2, 181.06, _top, 3.20, 3.20)

_SIGN_MANUAL_LAYOUT.update({
    'tax_no_income': (2, 181.59, 170.55, 3.20, 3.20),
    'tax_additional_income': (2, 181.59, 180.80, 3.20, 3.20),
    'tax_officer': (2, 181.59, 209.15, 3.20, 3.20),
})

for _definition in _SIGN_TEMPLATE_ITEMS:
    _layout = _SIGN_MANUAL_LAYOUT.get(_definition['key'])
    if _layout:
        (_definition['page'], _definition['left'], _definition['top'],
         _definition['width'], _definition['height']) = _layout

# Use Odoo's standard Sign item types.  Date, phone and email are distinct
# native types even though some of them are internally rendered as text.
_SIGN_DATE_KEYS = {
    'birthday', 'immigration_date', 'employment_start_date',
    'spouse_birthdate', 'spouse_immigration_date',
    'eligible_settlement_from', 'new_immigrant_from',
    'no_income_until_date', 'service_start_date', 'service_end_date',
    'declaration_date',
    *(f'child_{index}_birthday' for index in range(1, _SIGN_CHILD_ROW_COUNT + 1)),
}
_SIGN_PHONE_KEYS = {'employer_phone', 'private_phone', 'mobile_phone'}
for _definition in _SIGN_TEMPLATE_ITEMS:
    if _definition['key'] in _SIGN_DATE_KEYS:
        _definition['type_xmlid'] = 'sign.sign_item_type_date'
    elif _definition['key'] in _SIGN_PHONE_KEYS:
        _definition['type_xmlid'] = 'sign.sign_item_type_phone'
    elif _definition['key'] == 'private_email':
        _definition['type_xmlid'] = 'sign.sign_item_type_email'
    elif _definition['key'] == 'employer_name':
        _definition['type_xmlid'] = 'sign.sign_item_type_name'

# The three rows in "changes during the year" are part of the legal form even
# though they are informational and are not copied to the payroll record.
for _change_index, _change_top in enumerate((271.458, 277.398, 283.338), 1):
    _SIGN_TEMPLATE_ITEMS.extend([
        _sign_item(
            f'change_{_change_index}_date', f'שינוי {_change_index} - תאריך',
            False, 1, 171.57 if _change_index == 1 else (171.15 if _change_index == 2 else 171.36),
            _change_top, 17.01, type_xmlid='sign.sign_item_type_date'),
        _sign_item(
            f'change_{_change_index}_details', f'שינוי {_change_index} - פרטים',
            False, 1, 67.0, _change_top, 103.0),
        _sign_item(
            f'change_{_change_index}_notice_date', f'שינוי {_change_index} - תאריך הודעה',
            False, 1, 43.0, _change_top, 22.0,
            type_xmlid='sign.sign_item_type_date'),
        _sign_item(
            f'change_{_change_index}_signature', f'שינוי {_change_index} - חתימה',
            False, 1, 11.0, _change_top, 30.0,
            type_xmlid='sign.sign_item_type_signature'),
    ])


_SIGN_KEY_BY_AUTO_FIELD = {
    definition['auto_field']: definition['key']
    for definition in _SIGN_TEMPLATE_ITEMS
}

# These choices are mutually exclusive in the legal form. They are rendered
# as native Odoo Sign radio sets so choosing one immediately clears the other
# choices in the same group. The PDF still supplies the printed square boxes.
_SIGN_RADIO_GROUP_BY_KEY = {
    **{key: 'sex' for key in ('sex_male', 'sex_female')},
    **{key: 'marital' for key in (
        'marital_single', 'marital_married', 'marital_divorced',
        'marital_widower', 'marital_separated',
    )},
    **{key: 'resident' for key in ('resident_yes', 'resident_no')},
    **{key: 'kibbutz' for key in (
        'kibbutz_yes', 'kibbutz_no', 'kibbutz_not_transferred',
    )},
    **{key: 'health_fund' for key in (
        'health_fund_yes', 'health_fund_no',
    )},
    **{key: 'income' for key in (
        'income_monthly', 'income_additional', 'income_partial',
        'income_daily', 'income_pension', 'income_scholarship',
    )},
    **{key: 'other_income' for key in (
        'other_income_no', 'other_income_yes',
    )},
    **{key: 'spouse_income_status' for key in (
        'spouse_no_income', 'spouse_has_income_yes',
    )},
    **{key: 'credit_points' for key in (
        'credit_points_here', 'credit_points_elsewhere',
    )},
    **{key: 'tax_reason' for key in (
        'tax_no_income', 'tax_additional_income', 'tax_officer',
    )},
}

# Coordinates used by the immediately preceding layout.  They are kept only
# as stable aliases so an upgrade can identify and move the existing fields
# in place.  This preserves Sign item IDs and therefore also preserves the
# already-sent request while avoiding another Form 101 template.
_SIGN_LEGACY_POSITION_BY_KEY = {
    'health_fund_name': (1, 10.50, 111.55),
    'mobile_phone': (1, 38.70, 111.55),
    'private_phone': (1, 72.82, 111.55),
    'private_email': (1, 129.15, 111.078),
    'employment_start_date': (1, 12.00, 136.50),
    'spouse_no_income': (1, 144.30, 252.00),
    'spouse_has_income_yes': (1, 99.30, 252.00),
    'spouse_income_work': (1, 56.20, 252.00),
    'spouse_income_other': (1, 28.56, 253.64),
    'identity_number_page_2': (2, 31.20, 4.20),
    'custody_children_born': (2, 127.00, 80.40),
    'custody_children_age_1_2': (2, 96.00, 84.70),
    'custody_children_age_3': (2, 112.00, 88.70),
    'custody_children_age_4_5': (2, 13.00, 80.80),
    'custody_children_age_6_17': (2, 12.00, 84.70),
    'custody_children_age_18': (2, 25.00, 88.70),
    'other_children_born': (2, 127.00, 97.30),
    'other_children_age_1_2': (2, 96.00, 101.50),
    'other_children_age_3': (2, 112.00, 105.50),
    'other_children_age_4_5': (2, 13.00, 97.90),
    'other_children_age_6_17': (2, 12.00, 101.50),
    'reserve_combat_days': (2, 46.00, 157.80),
}
for _key, _top in {
    'relief_resident': 13.60,
    'relief_disabled_blind': 19.00,
    'relief_disabled_benefit': 26.90,
    'relief_eligible_settlement': 33.20,
    'relief_new_immigrant': 42.60,
    'relief_spouse_no_income': 56.50,
    'relief_single_parent_family': 64.40,
    'relief_children_in_custody': 72.70,
    'relief_other_children': 93.30,
    'relief_single_parent': 110.80,
    'relief_support_non_custody': 117.20,
    'relief_disabled_children': 125.90,
    'relief_alimony_former_spouse': 134.00,
    'relief_age_16_18': 139.80,
    'relief_discharged_service': 145.40,
    'relief_studies': 153.60,
    'relief_reserve_combat': 158.30,
}.items():
    _SIGN_LEGACY_POSITION_BY_KEY[_key] = (2, 180.00, _top)
_SIGN_LEGACY_POSITION_BY_KEY.update({
    'tax_no_income': (2, 180.50, 168.80),
    'tax_additional_income': (2, 180.50, 179.10),
    'tax_officer': (2, 180.50, 207.50),
})
for _child_index in range(1, 11):
    _legacy_child_top = 141.0 + (_child_index - 1) * 9.25
    _SIGN_LEGACY_POSITION_BY_KEY.update({
        f'child_{_child_index}_name': (1, 151.00, _legacy_child_top),
        f'child_{_child_index}_id': (1, 121.00, _legacy_child_top),
        f'child_{_child_index}_birthday': (1, 88.00, _legacy_child_top),
        f'child_{_child_index}_custody': (1, 183.80, _legacy_child_top),
        f'child_{_child_index}_allowance': (1, 187.40, _legacy_child_top),
    })
for _employer_index in range(1, 4):
    _legacy_employer_top = 192.5 + (_employer_index - 1) * 4.9
    _SIGN_LEGACY_POSITION_BY_KEY.update({
        f'other_employer_{_employer_index}_name': (2, 158.50, _legacy_employer_top),
        f'other_employer_{_employer_index}_address': (2, 111.00, _legacy_employer_top),
        f'other_employer_{_employer_index}_file': (2, 81.00, _legacy_employer_top),
        f'other_employer_{_employer_index}_type': (2, 62.00, _legacy_employer_top),
        f'other_employer_{_employer_index}_income': (2, 36.50, _legacy_employer_top),
        f'other_employer_{_employer_index}_tax': (2, 11.00, _legacy_employer_top),
    })


def _sign_item_size(definition):
    """Return a usable hit area without letting adjacent controls overlap."""
    if _SIGN_RADIO_GROUP_BY_KEY.get(definition['key']):
        return 3.6, 3.6
    return definition['width'], definition['height']


def _sign_definition_for_item(item):
    """Resolve a Sign item without custom item types or visible metadata.

    The canonical layout is stable while database record IDs are not.  A
    small tolerance protects against the harmless float rounding performed by
    the Sign editor.
    """
    if not item or item.page not in (1, 2):
        return False
    left = item.posX * 210
    top = item.posY * 297
    candidates = [
        definition for definition in _SIGN_TEMPLATE_ITEMS
        if definition['page'] == item.page
    ]
    if not candidates:
        return False
    def distance(candidate):
        points = [(candidate['page'], candidate['left'], candidate['top'])]
        legacy = _SIGN_LEGACY_POSITION_BY_KEY.get(candidate['key'])
        if legacy:
            points.append(legacy)
        return min(
            abs(point_left - left) + abs(point_top - top)
            for point_page, point_left, point_top in points
            if point_page == item.page
        )

    definition = min(candidates, key=distance)
    canonical_match = (
        abs(definition['left'] - left) <= 0.8
        and abs(definition['top'] - top) <= 0.8
    )
    legacy = _SIGN_LEGACY_POSITION_BY_KEY.get(definition['key'])
    legacy_match = bool(
        legacy
        and legacy[0] == item.page
        and abs(legacy[1] - left) <= 0.8
        and abs(legacy[2] - top) <= 0.8
    )
    return definition if canonical_match or legacy_match else False

class HrEmployeeForm101(models.Model):
    _name = 'hr.employee.form.101'
    _description = 'טופס 101'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'tax_year desc, id desc'
    _rec_name = 'display_name'

    _unique_active_employee = models.UniqueIndex(
        "(employee_id) WHERE state = 'active'",
        'לעובד יכול להיות טופס 101 פעיל אחד בלבד.',
    )

    display_name = fields.Char(compute='_compute_display_name')
    employee_id = fields.Many2one(
        'hr.employee', string='עובד', required=True, ondelete='cascade',
        index=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='חברה', related='employee_id.company_id',
        store=True, readonly=True)
    tax_year = fields.Selection(
        TAX_YEAR_SELECTION, string='שנת מס', required=True,
        default=lambda self: str(fields.Date.today().year),
        tracking=True)
    state = fields.Selection([
        ('draft', 'טיוטה'),
        ('sent', 'נשלח'),
        ('signed', 'נחתם'),
        ('active', 'פעיל'),
    ], string='סטטוס', default='draft', required=True, tracking=True, index=True)
    sign_template_id = fields.Many2one(
        'sign.template', string='תבנית חתימה', copy=False,
        default=lambda self: self._default_sign_template_id(),
        domain="[('active', '=', True)]")
    sign_request_id = fields.Many2one(
        'sign.request', string='בקשת חתימה', readonly=True, copy=False,
        ondelete='set null', tracking=True)
    form_file = fields.Binary(
        string='קובץ טופס 101', attachment=True, readonly=True, copy=False)
    form_filename = fields.Char(string='שם קובץ טופס 101', readonly=True, copy=False)
    employee_version_id = fields.Many2one(
        'hr.version', string='גרסת עובד שנוצרה', readonly=True, copy=False,
        ondelete='set null')

    for _sign_autofill_field in _SIGN_AUTOFILL_FIELDS:
        locals()[_sign_autofill_field] = fields.Char(
            compute='_compute_sign_autofill_values')

    # Part A - employer details (historical snapshot).
    employer_name = fields.Char(string='שם המעסיק', required=True)
    employer_address = fields.Char(string='כתובת המעסיק', required=True)
    employer_phone = fields.Char(string='טלפון המעסיק', required=True)
    employer_withholding_file = fields.Char(string='מספר תיק ניכויים', required=True)

    # Part B - employee details.
    has_israeli_id = fields.Selection(
        [('yes', 'כן'), ('no', 'לא')], string='יש מספר תעודת זהות',
        required=True, default='yes')
    identification_id = fields.Char(string='מספר זהות')
    passport_id = fields.Char(string='מספר דרכון')
    passport_country_id = fields.Many2one('res.country', string='מדינת הדרכון')
    identity_card_file = fields.Binary(
        string='צילום תעודת זהות וספח', attachment=True, copy=False)
    passport_file = fields.Binary(
        string='צילום דרכון', attachment=True, copy=False)
    residence_permit_file = fields.Binary(
        string='אישור / רישיון שהייה בישראל', attachment=True, copy=False)
    first_name = fields.Char(string='שם פרטי', required=True)
    last_name = fields.Char(string='שם משפחה', required=True)
    immigration_date = fields.Date(string='תאריך עלייה')
    birthday = fields.Date(string='תאריך לידה', required=True)
    private_street = fields.Char(string='רחוב / שכונה', required=True)
    private_house_number = fields.Char(string='מספר בית', required=True)
    private_city = fields.Char(string='עיר / יישוב', required=True)
    private_zip = fields.Char(string='מיקוד')
    private_country_id = fields.Many2one('res.country', string='מדינה')
    private_phone = fields.Char(string='מספר טלפון')
    mobile_phone = fields.Char(string='מספר טלפון נייד')
    private_email = fields.Char(string='דואר אלקטרוני')
    sex = fields.Selection(
        [('male', 'זכר'), ('female', 'נקבה')], string='מין', required=True)
    marital = fields.Selection(MARITAL_SELECTION, string='מצב משפחתי', required=True)
    is_israeli_resident = fields.Selection(
        [('yes', 'כן'), ('no', 'לא')], string='תושב/ת ישראל', required=True, default='yes')
    kibbutz_status = fields.Selection([
        ('no', 'לא'),
        ('income_transferred', 'כן, ההכנסות מועברות לקיבוץ'),
        ('income_not_transferred', 'כן, ההכנסות אינן מועברות לקיבוץ'),
    ], string='חבר/ת קיבוץ או מושב שיתופי', required=True, default='no')
    health_fund_member = fields.Selection(
        [('yes', 'כן'), ('no', 'לא')], string='חבר/ה בקופת חולים')
    health_fund_name = fields.Selection([
        ('כללית', 'כללית'),
        ('מכבי', 'מכבי'),
        ('מאוחדת', 'מאוחדת'),
        ('לאומית', 'לאומית'),
    ], string='שם קופת החולים')
    separated_tax_officer_certificate = fields.Binary(
        string='אישור פקיד שומה לפרוד/ה', attachment=True, copy=False)

    # Part C - children.
    child_ids = fields.One2many(
        'hr.employee.form.101.child', 'form_id', string='ילדים מתחת לגיל 19', copy=True)

    # Part D - income from this employer.
    employer_income_main_type = fields.Selection(
        INCOME_TYPE_SELECTION[:4], string='סוג משכורת אצל מעסיק זה')
    employer_income_pension = fields.Boolean(string='קצבה ממעסיק זה')
    employer_income_scholarship = fields.Boolean(string='מלגה ממעסיק זה')
    employment_start_date = fields.Date(
        string='תאריך תחילת העבודה בשנת המס', required=True)

    # Part E - other income.
    has_other_income = fields.Selection([
        ('no', 'אין לי הכנסות אחרות ממשכורת, קצבה או מלגה'),
        ('yes', 'יש לי הכנסות אחרות'),
    ], string='הכנסות אחרות', required=True)
    other_income_monthly = fields.Boolean(string='משכורת חודש')
    other_income_additional = fields.Boolean(string='משכורת בעד משרה נוספת')
    other_income_partial = fields.Boolean(string='משכורת חלקית')
    other_income_daily = fields.Boolean(string='שכר עבודה (עובד יומי)')
    other_income_pension = fields.Boolean(string='קצבה ממקור אחר')
    other_income_scholarship = fields.Boolean(string='מלגה ממקור אחר')
    other_income_other_details = fields.Char(string='פירוט מקור הכנסה אחר')
    credit_points_here = fields.Selection([
        ('here', 'אבקש נקודות זיכוי ומדרגות מס כנגד הכנסה זו'),
        ('elsewhere', 'אני מקבל/ת אותן בהכנסה אחרת'),
    ], string='נקודות זיכוי ומדרגות מס')
    no_study_fund_elsewhere = fields.Boolean(
        string='אין הפרשות לקרן השתלמות בהכנסה האחרת')
    no_pension_elsewhere = fields.Boolean(
        string='אין הפרשות לקצבה/אובדן כושר/פיצויים בהכנסה האחרת')

    # Part F - spouse.
    spouse_has_israeli_id = fields.Selection(
        [('yes', 'כן'), ('no', 'לא')], string='לבן/בת הזוג יש תעודת זהות',
        default='yes')
    spouse_identification_id = fields.Char(string='מספר זהות בן/בת זוג')
    spouse_passport_id = fields.Char(string='מספר דרכון בן/בת זוג')
    spouse_passport_country_id = fields.Many2one(
        'res.country', string='מדינת הדרכון של בן/בת הזוג')
    spouse_first_name = fields.Char(string='שם פרטי בן/בת זוג')
    spouse_last_name = fields.Char(string='שם משפחה בן/בת זוג')
    spouse_birthdate = fields.Date(string='תאריך לידה בן/בת זוג')
    spouse_immigration_date = fields.Date(string='תאריך עלייה בן/בת זוג')
    spouse_has_income = fields.Selection([
        ('no', 'אין לבן/בת הזוג כל הכנסה'),
        ('yes', 'יש לבן/בת הזוג הכנסה'),
    ], string='הכנסת בן/בת זוג')
    spouse_income_work = fields.Boolean(string='עבודה / קצבה / עסק')
    spouse_income_other = fields.Boolean(string='הכנסה אחרת')

    # Part H - exemptions and credits.
    relief_resident = fields.Boolean(string='1. אני תושב/ת ישראל')
    relief_disabled_blind = fields.Boolean(string='2א. נכה 100% או עיוור/ת לצמיתות')
    disabled_blind_certificate = fields.Binary(
        string='אישור נכות / עיוורון', attachment=True, copy=False)
    relief_disabled_benefit = fields.Boolean(string='2ב. מקבל/ת תגמול חודשי לפי חוקי הנכים')
    disabled_benefit_certificate = fields.Binary(
        string='אישור על קבלת תגמול חודשי', attachment=True, copy=False)
    relief_eligible_settlement = fields.Boolean(string='3. תושב/ת קבוע/ה ביישוב מזכה')
    eligible_settlement_name = fields.Char(string='שם היישוב המזכה')
    eligible_settlement_from = fields.Date(string='מתאריך')
    eligible_settlement_certificate = fields.Binary(
        string='אישור יישוב מזכה - טופס 1312א', attachment=True, copy=False)
    relief_new_immigrant = fields.Boolean(string='4. עולה חדש/ה')
    new_immigrant_from = fields.Date(string='מתאריך עלייה לצורך הזיכוי')
    no_income_until_date = fields.Date(string='לא הייתה הכנסה בישראל עד תאריך')
    new_immigrant_certificate = fields.Binary(
        string='תעודת עולה', attachment=True, copy=False)
    returning_resident_certificate = fields.Binary(
        string='אישור תושב חוזר', attachment=True, copy=False)
    relief_spouse_no_income = fields.Boolean(string='5. בן/בת זוג ללא הכנסה')
    spouse_disability_certificate = fields.Binary(
        string='אישור נכה או עיוור לעובד/ת או לבן/בת הזוג',
        attachment=True, copy=False)
    relief_single_parent_family = fields.Boolean(string='6. הורה במשפחה חד-הורית החי בנפרד')
    relief_children_in_custody = fields.Boolean(string='7. ילדים שבחזקתי')
    custody_children_born = fields.Integer(string='בחזקתי - נולדו בשנת המס')
    custody_children_age_1_2 = fields.Integer(string='בחזקתי - בני שנה עד שנתיים')
    custody_children_age_3 = fields.Integer(string='בחזקתי - בני 3')
    custody_children_age_4_5 = fields.Integer(string='בחזקתי - בני 4 עד 5')
    custody_children_age_6_17 = fields.Integer(string='בחזקתי - בני 6 עד 17')
    custody_children_age_18 = fields.Integer(string='בחזקתי - בני 18')
    relief_other_children = fields.Boolean(string='8. בגין ילדיי (שאינם בסעיף 7)')
    other_children_born = fields.Integer(string='ילדים אחרים - נולדו בשנת המס')
    other_children_age_1_2 = fields.Integer(string='ילדים אחרים - בני שנה עד שנתיים')
    other_children_age_3 = fields.Integer(string='ילדים אחרים - בני 3')
    other_children_age_4_5 = fields.Integer(string='ילדים אחרים - בני 4 עד 5')
    other_children_age_6_17 = fields.Integer(string='ילדים אחרים - בני 6 עד 17')
    relief_single_parent = fields.Boolean(string='9. הורה יחיד לילדיי שבחזקתי')
    relief_support_non_custody = fields.Boolean(string='10. משתתף/ת בכלכלת ילדים שאינם בחזקתי')
    child_support_judgment = fields.Binary(
        string='פסק דין לתשלום מזונות ילדים', attachment=True, copy=False)
    relief_disabled_children = fields.Boolean(string='11. ילדים עם מוגבלות')
    disabled_children_count = fields.Integer(string='מספר ילדים עם מוגבלות')
    disabled_child_benefit_certificate = fields.Binary(
        string='אישור גמלת ילד נכה', attachment=True, copy=False)
    relief_alimony_former_spouse = fields.Boolean(string='12. מזונות לבן/בת זוג לשעבר')
    former_spouse_alimony_judgment = fields.Binary(
        string='פסק דין למזונות בן/בת זוג לשעבר', attachment=True, copy=False)
    relief_age_16_18 = fields.Boolean(string='13. העובד/ת או בן/בת הזוג בני 16 עד 18')
    relief_discharged_service = fields.Boolean(string='14. חייל/ת משוחרר/ת או שירות לאומי')
    service_start_date = fields.Date(string='תאריך תחילת השירות')
    service_end_date = fields.Date(string='תאריך סיום השירות')
    discharge_certificate = fields.Binary(
        string='תעודת שחרור / סיום שירות', attachment=True, copy=False)
    relief_studies = fields.Boolean(string='15. סיום לימודים / התמחות / לימודי מקצוע')
    studies_form_119 = fields.Binary(
        string='הצהרה בטופס 119', attachment=True, copy=False)
    relief_reserve_combat = fields.Boolean(string='16. שירות מילואים כלוחם/ת')
    reserve_combat_days = fields.Integer(string='סה״כ ימי מילואים בשנת המס הקודמת')
    reserve_combat_certificate = fields.Binary(
        string='אישור זכאות מצה״ל לשירות מילואים כלוחם',
        attachment=True, copy=False)

    # Part I - tax coordination.
    tax_coordination_requested = fields.Boolean(string='צירוף / עריכת תיאום מס')
    tax_coordination_reason = fields.Selection([
        ('no_income', 'לא הייתה הכנסה מתחילת שנת המס עד תחילת העבודה'),
        ('additional_income', 'יש לי הכנסות נוספות ממשכורת'),
        ('tax_officer', 'פקיד השומה אישר תיאום מס'),
    ], string='סיבת הבקשה לתיאום מס')
    other_employer_ids = fields.One2many(
        'hr.employee.form.101.other.employer', 'form_id', string='מעסיקים / משלמים נוספים', copy=True)
    no_previous_income_certificate = fields.Binary(
        string='הוכחות לחוסר הכנסה', attachment=True, copy=False)
    tax_officer_coordination_certificate = fields.Binary(
        string='אישור תיאום מס מפקיד השומה', attachment=True, copy=False)

    # Part J and supporting documents.
    declaration_confirmed = fields.Boolean(
        string='אני מאשר/ת את הצהרת העובד', required=True)
    declaration_date = fields.Date(string='תאריך ההצהרה', required=True)
    employee_signature = fields.Binary(
        string='חתימת העובד', attachment=True, copy=False)
    employee_signature_date = fields.Date(
        string='תאריך חתימת העובד', readonly=True, copy=False)
    attachment_ids = fields.Many2many(
        'ir.attachment', 'hr_employee_form_101_attachment_rel',
        'form_id', 'attachment_id', string='מסמכים מצורפים')
    notes = fields.Text(string='הערות')

    _VERSION_FIELD_MAP = {
        'identification_id': 'identification_id',
        'passport_id': 'passport_id',
        'sex': 'sex',
        'private_street': 'private_street',
        'private_house_number': 'private_street2',
        'private_city': 'private_city',
        'private_zip': 'private_zip',
        'private_country_id': 'private_country_id',
        'marital': 'marital',
        'spouse_birthdate': 'spouse_birthdate',
    }
    _EMPLOYEE_FIELD_MAP = {
        'birthday': 'birthday',
        'private_phone': 'private_phone',
        'mobile_phone': 'mobile_phone',
        'private_email': 'private_email',
    }

    @api.depends('employee_id', 'tax_year')
    def _compute_display_name(self):
        for form in self:
            form.display_name = _('%(employee)s - טופס 101 %(year)s',
                                  employee=form.employee_id.name or '', year=form.tax_year or '')

    @api.model
    def _default_sign_template_id(self):
        installed_template = self.env.ref(
            'l10n_il_hr_payroll.sign_template_form_101',
            raise_if_not_found=False,
        )
        if installed_template and installed_template.active:
            return installed_template.id
        return self.env['sign.template'].search([
            ('active', '=', True),
            ('name', 'ilike', '101'),
            ('model_id.model', '=', self._name),
        ], order='id desc', limit=1).id

    def _compute_sign_autofill_values(self):
        check = lambda value: '✓' if value else ''
        income_labels = dict(INCOME_TYPE_SELECTION)
        for form in self:
            values = {
                'sign_full_address': ' '.join(filter(None, (
                    form.private_street, form.private_house_number, form.private_city))),
                'sign_identity_number': form.identification_id or form.passport_id or '',
                'sign_sex_male': check(form.sex == 'male'),
                'sign_sex_female': check(form.sex == 'female'),
                'sign_marital_single': check(form.marital == 'single'),
                'sign_marital_married': check(form.marital == 'married'),
                'sign_marital_divorced': check(form.marital == 'divorced'),
                'sign_marital_widower': check(form.marital == 'widower'),
                'sign_marital_separated': check(form.marital == 'separated'),
                'sign_resident_yes': check(form.is_israeli_resident == 'yes'),
                'sign_resident_no': check(form.is_israeli_resident == 'no'),
                'sign_kibbutz_yes': check(form.kibbutz_status == 'income_transferred'),
                'sign_kibbutz_no': check(form.kibbutz_status == 'no'),
                'sign_kibbutz_not_transferred': check(
                    form.kibbutz_status == 'income_not_transferred'),
                'sign_health_fund_yes': check(form.health_fund_member == 'yes'),
                'sign_health_fund_no': check(form.health_fund_member == 'no'),
                'sign_income_monthly': check(form.employer_income_main_type == 'monthly'),
                'sign_income_additional': check(form.employer_income_main_type == 'additional'),
                'sign_income_partial': check(form.employer_income_main_type == 'partial'),
                'sign_income_daily': check(form.employer_income_main_type == 'daily'),
                'sign_income_pension': check(form.employer_income_pension),
                'sign_income_scholarship': check(form.employer_income_scholarship),
                'sign_other_income_no': check(form.has_other_income == 'no'),
                'sign_other_income_yes': check(form.has_other_income == 'yes'),
                'sign_other_income_monthly': check(form.other_income_monthly),
                'sign_other_income_additional': check(form.other_income_additional),
                'sign_other_income_partial': check(form.other_income_partial),
                'sign_other_income_daily': check(form.other_income_daily),
                'sign_other_income_pension': check(form.other_income_pension),
                'sign_other_income_scholarship': check(form.other_income_scholarship),
                'sign_credit_points_here': check(form.credit_points_here == 'here'),
                'sign_credit_points_elsewhere': check(form.credit_points_here == 'elsewhere'),
                'sign_no_study_fund_elsewhere': check(form.no_study_fund_elsewhere),
                'sign_no_pension_elsewhere': check(form.no_pension_elsewhere),
                'sign_spouse_no_income': check(form.spouse_has_income == 'no'),
                'sign_spouse_has_income_yes': check(form.spouse_has_income == 'yes'),
                'sign_spouse_income_work': check(form.spouse_income_work),
                'sign_spouse_income_other': check(form.spouse_income_other),
                'sign_relief_resident': check(form.relief_resident),
                'sign_relief_disabled_blind': check(form.relief_disabled_blind),
                'sign_relief_disabled_benefit': check(form.relief_disabled_benefit),
                'sign_relief_eligible_settlement': check(form.relief_eligible_settlement),
                'sign_relief_new_immigrant': check(form.relief_new_immigrant),
                'sign_relief_spouse_no_income': check(form.relief_spouse_no_income),
                'sign_relief_single_parent_family': check(form.relief_single_parent_family),
                'sign_relief_children_in_custody': check(form.relief_children_in_custody),
                'sign_relief_other_children': check(form.relief_other_children),
                'sign_relief_single_parent': check(form.relief_single_parent),
                'sign_relief_support_non_custody': check(form.relief_support_non_custody),
                'sign_relief_disabled_children': check(form.relief_disabled_children),
                'sign_relief_alimony_former_spouse': check(form.relief_alimony_former_spouse),
                'sign_relief_age_16_18': check(form.relief_age_16_18),
                'sign_relief_discharged_service': check(form.relief_discharged_service),
                'sign_relief_studies': check(form.relief_studies),
                'sign_relief_reserve_combat': check(form.relief_reserve_combat),
                'sign_tax_no_income': check(form.tax_coordination_reason == 'no_income'),
                'sign_tax_additional_income': check(form.tax_coordination_reason == 'additional_income'),
                'sign_tax_officer': check(form.tax_coordination_reason == 'tax_officer'),
            }
            children = form.child_ids[:_SIGN_CHILD_ROW_COUNT]
            for index in range(1, _SIGN_CHILD_ROW_COUNT + 1):
                child = children[index - 1] if len(children) >= index else False
                values.update({
                    f'sign_child_{index}_name': child.name if child else '',
                    f'sign_child_{index}_identification_id': child.identification_id if child else '',
                    f'sign_child_{index}_birthday': fields.Date.to_string(child.birthday) if child and child.birthday else '',
                    f'sign_child_{index}_custody': check(child and child.in_custody),
                    f'sign_child_{index}_allowance': check(child and child.receives_child_allowance),
                })
            employers = form.other_employer_ids[:3]
            for index in range(1, 4):
                employer = employers[index - 1] if len(employers) >= index else False
                values.update({
                    f'sign_other_employer_{index}_name': employer.name if employer else '',
                    f'sign_other_employer_{index}_address': employer.address if employer else '',
                    f'sign_other_employer_{index}_withholding_file': employer.withholding_file if employer else '',
                    f'sign_other_employer_{index}_income_type': income_labels.get(employer.income_type, '') if employer else '',
                    f'sign_other_employer_{index}_monthly_income': str(employer.monthly_income or '') if employer else '',
                    f'sign_other_employer_{index}_tax_withheld': str(employer.tax_withheld or '') if employer else '',
                })
            for field_name in _SIGN_AUTOFILL_FIELDS:
                form[field_name] = values.get(field_name, '')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for form in self.filtered('employee_id'):
            form.update(form._employee_snapshot_values(form.employee_id))

    @api.onchange('is_israeli_resident')
    def _onchange_is_israeli_resident(self):
        if self.is_israeli_resident == 'yes':
            self.relief_resident = True
        elif self.is_israeli_resident == 'no':
            self.relief_resident = False

    @api.onchange('has_other_income')
    def _onchange_has_other_income(self):
        if self.has_other_income == 'no':
            self.update({name: False for name in (
                'other_income_monthly', 'other_income_additional', 'other_income_partial',
                'other_income_daily', 'other_income_pension', 'other_income_scholarship',
                'credit_points_here', 'no_study_fund_elsewhere', 'no_pension_elsewhere')})

    @api.model
    def _employee_snapshot_values(self, employee):
        version = employee.version_id
        legal_name = employee.legal_name or employee.name or ''
        return {
            'first_name': legal_name,
            'last_name': False,
            'identification_id': version.identification_id,
            'passport_id': version.passport_id,
            'birthday': employee.birthday,
            'private_street': version.private_street,
            'private_house_number': version.private_street2,
            'private_city': version.private_city,
            'private_zip': version.private_zip,
            'private_country_id': version.private_country_id.id,
            'private_phone': employee.private_phone,
            'mobile_phone': employee.mobile_phone,
            'private_email': employee.private_email,
            'sex': version.sex if version.sex in ('male', 'female') else False,
            'marital': version.marital,
            'spouse_first_name': version.spouse_complete_name,
            'spouse_birthdate': version.spouse_birthdate,
            'employer_name': employee.company_id.name,
            'employer_address': employee.company_id.partner_id.contact_address,
            'employer_phone': employee.company_id.phone,
            'employment_start_date': version.contract_date_start,
            'has_israeli_id': 'yes' if version.identification_id else 'no',
            'is_israeli_resident': 'yes' if version.private_country_id.code == 'IL' else 'no',
            'relief_resident': version.private_country_id.code == 'IL',
        }

    @api.model_create_multi
    def create(self, vals_list):
        complete_vals_list = []
        for incoming in vals_list:
            vals = dict(incoming)
            if vals.get('employee_id'):
                employee = self.env['hr.employee'].browse(vals['employee_id'])
                snapshot = self._employee_snapshot_values(employee)
                snapshot.update(vals)
                vals = snapshot
            complete_vals_list.append(vals)
        return super().create(complete_vals_list)

    def write(self, vals):
        internal_fields = {
            'state', 'activity_ids', 'message_follower_ids', 'message_partner_ids',
            'message_ids', 'message_main_attachment_id', 'employee_version_id',
            'sign_request_id', 'form_file', 'form_filename',
            'sign_template_id', 'employee_signature', 'employee_signature_date',
        }
        if (not self.env.context.get('form_101_system_write')
                and self.filtered(lambda form: form.state != 'draft') and any(
                key not in internal_fields for key in vals)):
            raise ValidationError(_('ניתן לערוך את טופס 101 רק במצב טיוטה. יש להחזיר אותו לטיוטה לפני השינוי.'))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        if self.filtered(lambda form: form.state != 'draft'):
            raise ValidationError(_(
                'ניתן למחוק רק טופס 101 שנמצא במצב טיוטה.'))

    def _employee_update_values(self):
        self.ensure_one()
        version_vals = {}
        employee_vals = {}
        current_version = self.employee_id.version_id
        for form_field, employee_field in self._VERSION_FIELD_MAP.items():
            value = self[form_field]
            comparable = value.id if hasattr(value, 'id') else value
            current = current_version[employee_field]
            current_comparable = current.id if hasattr(current, 'id') else current
            if comparable != current_comparable:
                version_vals[employee_field] = comparable
        spouse_name = ' '.join(filter(None, [self.spouse_first_name, self.spouse_last_name]))
        if spouse_name != (current_version.spouse_complete_name or ''):
            version_vals['spouse_complete_name'] = spouse_name
        child_count = len(self.child_ids)
        if child_count != current_version.children:
            version_vals['children'] = child_count
        for form_field, employee_field in self._EMPLOYEE_FIELD_MAP.items():
            value = self[form_field]
            if value != self.employee_id[employee_field]:
                employee_vals[employee_field] = value
        legal_name = ' '.join(filter(None, [self.first_name, self.last_name]))
        if legal_name and legal_name != (self.employee_id.legal_name or self.employee_id.name or ''):
            employee_vals['legal_name'] = legal_name
        return version_vals, employee_vals

    def _il_is_primary_payroll_income(self):
        """Whether this employer receives the employee's brackets/credits.

        With no other income this is necessarily the primary payroll.  When
        another income exists, Part E of Form 101 explicitly decides where
        the brackets and credit points are used.
        """
        self.ensure_one()
        return (
            self.has_other_income != 'yes'
            or self.credit_points_here == 'here'
        )

    @staticmethod
    def _il_child_credit_points(form, prefix):
        """Return the statutory child credits represented by Part H.

        ``custody`` is the first column in the Tax Authority table and
        ``other`` is the second column.  The 2024+ table is also applicable
        to tax year 2026.
        """
        rates = {
            'born': 2.5,
            'age_1_2': 4.5,
            'age_3': 3.5,
            'age_4_5': 2.5,
            'age_6_17': 2.0 if prefix == 'custody' else 1.0,
        }
        points = sum(
            max(form['%s_children_%s' % (prefix, age_group)], 0) * rate
            for age_group, rate in rates.items()
        )
        if prefix == 'custody':
            points += max(form.custody_children_age_18, 0) * 0.5
        return points

    def _il_new_immigrant_credit_points(self, payroll_date):
        self.ensure_one()
        if not self.relief_new_immigrant or not self.new_immigrant_from:
            return 0.0
        start = self.no_income_until_date or self.new_immigrant_from
        if payroll_date < start:
            return 0.0
        elapsed_months = (
            (payroll_date.year - start.year) * 12
            + payroll_date.month - start.month
        )
        if elapsed_months < 18:
            return 3.0
        if elapsed_months < 30:
            return 2.0
        if elapsed_months < 42:
            return 1.0
        return 0.0

    def _il_discharged_service_credit_points(self, payroll_date):
        self.ensure_one()
        if (not self.relief_discharged_service or not self.service_start_date
                or not self.service_end_date or payroll_date <= self.service_end_date):
            return 0.0
        elapsed_months = (
            (payroll_date.year - self.service_end_date.year) * 12
            + payroll_date.month - self.service_end_date.month
        )
        if elapsed_months < 1 or elapsed_months > 36:
            return 0.0
        service_months = (
            (self.service_end_date.year - self.service_start_date.year) * 12
            + self.service_end_date.month - self.service_start_date.month
        )
        full_service_months = 22 if self.sex == 'female' else 23
        if service_months >= full_service_months:
            return 2.0
        return 1.0 if service_months >= 12 else 0.0

    def _il_reserve_credit_points(self, payroll_date):
        self.ensure_one()
        if not self.relief_reserve_combat:
            return 0.0
        days = max(self.reserve_combat_days, 0)
        if payroll_date.year in (2026, 2027):
            if days < 30:
                return 0.0
            if days < 40:
                return 0.5
            if days < 50:
                return 0.75
            return min(1.0 + ((days - 50) // 5) * 0.25, 4.0)
        if payroll_date.year >= 2028:
            if days < 20:
                return 0.0
            return min(0.75 + ((days - 20) // 5) * 0.25, 4.0)
        return 0.0

    def _il_payroll_credit_points(self, payroll_date):
        """Credit points declared by this active Form 101 for one month.

        Only deterministic benefits that can be calculated from the fields
        on Form 101 are included. Benefits whose amount depends on an
        external approval (for example an eligible-settlement ceiling or a
        tax-officer coordination) remain represented by the existing manual
        payroll adjustment fields and are not guessed here.
        """
        self.ensure_one()
        payroll_date = fields.Date.to_date(payroll_date)
        if (self.state != 'active' or not self.tax_year
                or int(self.tax_year) != payroll_date.year
                or not self._il_is_primary_payroll_income()):
            return 0.0

        points = 0.0
        if self.relief_resident:
            points += 2.25
            if self.sex == 'female':
                points += 0.5
        if self.relief_spouse_no_income:
            points += 1.0
        if self.relief_single_parent_family:
            points += 1.0
        if self.relief_children_in_custody:
            points += self._il_child_credit_points(self, 'custody')
        if self.relief_other_children:
            points += self._il_child_credit_points(self, 'other')
        if self.relief_single_parent:
            # A child with only one registered/living parent receives both
            # parents' columns.  The first column was counted above.
            points += self._il_child_credit_points(self, 'other')
        if self.relief_support_non_custody:
            points += 1.0
        if self.relief_disabled_children:
            points += max(self.disabled_children_count, 0) * 2.0
        if self.relief_alimony_former_spouse:
            points += 1.0
        if self.relief_age_16_18:
            points += 1.0
        if self.relief_studies:
            points += 1.0
        points += self._il_new_immigrant_credit_points(payroll_date)
        points += self._il_discharged_service_credit_points(payroll_date)
        points += self._il_reserve_credit_points(payroll_date)
        return points

    def _apply_to_employee_if_needed(self):
        for form in self.filtered('employee_id'):
            version_vals, employee_vals = form._employee_update_values()
            if not version_vals and not employee_vals:
                continue
            employee = form.employee_id
            effective_date = fields.Date.context_today(form)
            current_today = employee.version_ids.filtered(
                lambda version: version.active and version.date_version == effective_date)
            if current_today:
                new_version = current_today[:1]
                if version_vals:
                    new_version.write(version_vals)
            else:
                new_version = employee.create_version({
                    'date_version': effective_date,
                    **version_vals,
                })
            if employee_vals:
                employee.write(employee_vals)
            form.with_context(skip_form_101_employee_sync=True).write({
                'employee_version_id': new_version.id,
            })

    @api.model
    def _set_form_101_xmlid(self, name, record):
        model_data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'l10n_il_hr_payroll'),
            ('name', '=', name),
        ], limit=1)
        values = {
            'module': 'l10n_il_hr_payroll',
            'name': name,
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        }
        if model_data:
            model_data.write(values)
        else:
            self.env['ir.model.data'].sudo().create(values)

    @api.model
    def _ensure_form_101_sign_template(self):
        linked_template = self.env.ref(
            'l10n_il_hr_payroll.sign_template_form_101',
            raise_if_not_found=False,
        )
        form_model = self.env['ir.model']._get(self._name)
        # The administrator-approved visible template is authoritative.  An
        # older archived XML-ID target must never replace it during upgrade.
        template = self.env['sign.template'].sudo().search([
            ('active', '=', True),
            ('model_id', '=', form_model.id),
        ], order='id desc', limit=1)
        created = False
        if not template and linked_template and linked_template.active:
            template = linked_template
        if not template:
            # Prefer the clean template positioned by the administrator.  It
            # is the authoritative visual reference and must not be replaced
            # by a second generated template.
            template = self.env['sign.template'].sudo().search([
                ('active', '=', True),
                ('name', 'ilike', '101'),
                ('sign_request_ids', '=', False),
            ], order='id desc', limit=1)
        if not template:
            with file_open(
                    'l10n_il_hr_payroll/static/src/pdf/form_101.pdf', 'rb') as pdf_file:
                pdf_data = base64.b64encode(pdf_file.read())
            result = self.env['sign.template'].sudo().with_context(
                default_model_name=self._name,
            ).create_from_attachment_data([{
                'name': _('תבנית טופס 101.pdf'),
                'datas': pdf_data,
            }])
            template = self.env['sign.template'].sudo().browse(result['id'])
            created = True
        template.sudo().write({
            'active': True,
            'model_id': form_model.id,
        })
        self._set_form_101_xmlid('sign_template_form_101', template)
        # Existing active templates may contain administrator-approved
        # millimetre adjustments.  Configure only a newly installed template;
        # module updates must preserve the visible template as-is.
        if created:
            self._ensure_sign_template_configuration(template)
        return template

    @api.model
    def _replace_spouse_other_income_checkbox(self, template=None):
        """Repair the four spouse-income controls without rebuilding the template."""
        template = template or self._ensure_form_101_sign_template()
        document = template.document_ids[:1]
        signature = document.sign_item_ids.filtered(
            lambda item: item.page == 2
            and item.type_id.item_type == 'signature')[:1]
        employee_role = (signature.responsible_id if signature else False) or self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_form_101_employee')
        definitions = {
            item['key']: item for item in _SIGN_TEMPLATE_ITEMS
            if item['key'] in {
                'spouse_no_income', 'spouse_has_income_yes',
                'spouse_income_work', 'spouse_income_other',
            }
        }
        row_items = document.sign_item_ids.filtered(
            lambda item: item.page == 1
            and item.type_id.item_type in ('checkbox', 'radio')
            and abs(item.posY * 297 - 253.60) <= 2.5
            and 20 <= item.posX * 210 <= 155
        )
        assigned = {}
        remaining = row_items
        for key in (
                'spouse_no_income', 'spouse_has_income_yes',
                'spouse_income_work', 'spouse_income_other'):
            definition = definitions[key]
            candidate = remaining.sorted(
                lambda item: abs(item.posX * 210 - definition['left']))[:1]
            if candidate and abs(candidate.posX * 210 - definition['left']) <= 4.0:
                assigned[key] = candidate
                remaining -= candidate
            else:
                assigned[key] = self.env['sign.item'].sudo().create({
                    'document_id': document.id,
                    'type_id': self.env.ref('sign.sign_item_type_checkbox').id,
                    'responsible_id': employee_role.id,
                    'page': 1,
                    'posX': definition['left'] / 210,
                    'posY': definition['top'] / 297,
                    'width': definition['width'] / 210,
                    'height': definition['height'] / 297,
                    'required': False,
                    'constant': False,
                    'alignment': 'center',
                    'name': False,
                    'radio_set_id': False,
                    'l10n_il_form_101_radio': False,
                })

        no_income_radio_set = assigned['spouse_no_income'].radio_set_id
        has_income_radio_set = assigned['spouse_has_income_yes'].radio_set_id
        radio_set = (
            no_income_radio_set
            if no_income_radio_set and no_income_radio_set == has_income_radio_set
            else self.env['sign.item.radio.set'].sudo().create({})
        )
        for key, item in assigned.items():
            definition = definitions[key]
            is_radio = key in ('spouse_no_income', 'spouse_has_income_yes')
            item.sudo().write({
                'type_id': self.env.ref(
                    'sign.sign_item_type_radio' if is_radio
                    else 'sign.sign_item_type_checkbox').id,
                'responsible_id': employee_role.id,
                'page': 1,
                'posX': definition['left'] / 210,
                'posY': definition['top'] / 297,
                'width': (3.6 if is_radio else 3.2) / 210,
                'height': (3.6 if is_radio else 3.2) / 297,
                'required': False,
                'constant': False,
                'alignment': 'center',
                'name': False,
                'radio_set_id': radio_set.id if is_radio else False,
                'l10n_il_form_101_radio': is_radio,
            })
        return template

    @api.model
    def _delete_archived_form_101_templates(self, keep_template):
        """Permanently remove every archived Form 101 template and history."""
        form_model = self.env['ir.model']._get(self._name)
        archived = self.env['sign.template'].sudo().with_context(
            active_test=False).search([
                ('model_id', '=', form_model.id),
                ('active', '=', False),
                ('id', '!=', keep_template.id),
            ])
        if not archived:
            return 0
        self.search([('sign_template_id', 'in', archived.ids)]).write({
            'sign_template_id': keep_template.id,
        })
        archived.sign_request_ids.sudo().unlink()
        count = len(archived)
        archived.unlink()
        return count

    @api.model
    def _ensure_form_101_assets(self):
        template = self._ensure_form_101_sign_template()
        self._replace_spouse_other_income_checkbox(template)
        self.search([('sign_request_id', '=', False)]).write({
            'sign_template_id': template.id,
        })
        return template

    @api.model
    def _update_form_101_sign_layout_in_place(self, template):
        """Move and retype the canonical fields without replacing a template.

        A sent Sign request points to the template's item IDs.  Updating those
        records is the only way to correct its layout while keeping one Form
        101 template and retaining any values already entered in the request.
        """
        document = template.document_ids[:1]
        signature = document.sign_item_ids.filtered(
            lambda item: item.page == 2
            and item.type_id.item_type == 'signature')[:1]
        items_by_key = {}
        stale_items = self.env['sign.item']
        for item in document.sign_item_ids.filtered(
                lambda record: record.page in (1, 2) and record != signature):
            definition = _sign_definition_for_item(item)
            if definition and definition['key'] not in items_by_key:
                items_by_key[definition['key']] = item
            else:
                stale_items |= item
        employee_role = (signature.responsible_id if signature else False) or self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_form_101_employee')
        # New legal rows are added to the same document.  Existing item IDs
        # remain untouched, so there is still exactly one Form 101 template.
        item_model = self.env['sign.item'].sudo()
        for definition in _SIGN_TEMPLATE_ITEMS:
            if definition['key'] in items_by_key:
                continue
            items_by_key[definition['key']] = item_model.create({
                'document_id': document.id,
                'type_id': self.env.ref(definition['type_xmlid']).id,
                'responsible_id': employee_role.id,
                'page': definition['page'],
                'posX': definition['left'] / 210,
                'posY': definition['top'] / 297,
                'width': definition['width'] / 210,
                'height': definition['height'] / 297,
                'required': False,
                'constant': False,
                'alignment': 'center',
                'name': False,
                'radio_set_id': False,
                'l10n_il_form_101_radio': False,
            })
        radio_sets = {
            group: self.env['sign.item.radio.set'].sudo().create({})
            for group in set(_SIGN_RADIO_GROUP_BY_KEY.values())
        }
        for definition in _SIGN_TEMPLATE_ITEMS:
            radio_group = _SIGN_RADIO_GROUP_BY_KEY.get(definition['key'])
            width, height = _sign_item_size(definition)
            items_by_key[definition['key']].sudo().write({
                'type_id': self.env.ref(
                    'sign.sign_item_type_radio'
                    if radio_group else definition['type_xmlid']).id,
                'responsible_id': employee_role.id,
                'page': definition['page'],
                'posX': definition['left'] / 210,
                'posY': definition['top'] / 297,
                'width': width / 210,
                'height': height / 297,
                'required': bool(
                    definition['auto_field']
                    and definition['auto_field'] in self._fields
                    and self._fields[definition['auto_field']].required
                ),
                'constant': False,
                'alignment': 'center',
                'name': False,
                'radio_set_id': radio_sets[radio_group].id
                if radio_group else False,
                'l10n_il_form_101_radio': bool(radio_group),
            })
        # Remove stale editor remnants and duplicate fields only after every
        # canonical field is present.  This keeps one precise editable layer.
        if stale_items:
            stale_items.sudo().unlink()
        if signature:
            signature.sudo().write({
                'responsible_id': employee_role.id,
                'posX': 11.97 / 210,
                'posY': 226.017 / 297,
                'width': 31.08 / 210,
                'height': 5.346 / 297,
                'required': True,
                'constant': False,
                'alignment': 'center',
                'name': False,
            })
        return template

    @api.model
    def _upgrade_form_101_sign_template_layout(self):
        """Install a new layout without mutating documents already sent.

        Odoo Sign requests retain their template item IDs.  When a template
        has requests, changing its items would corrupt the historical request,
        so layout migrations create one new active template version and
        archive the old version instead.
        """
        template = self.env.ref(
            'l10n_il_hr_payroll.sign_template_form_101',
            raise_if_not_found=False,
        )
        form_model = self.env['ir.model']._get(self._name)
        all_templates = self.env['sign.template'].sudo().with_context(
            active_test=False).search([('model_id', '=', form_model.id)])
        if template and template.sign_request_ids:
            # Keep the same template and item IDs.  In particular, do not
            # create a second visible template merely because a request was
            # already sent from this one.
            self._update_form_101_sign_layout_in_place(template)
            (all_templates - template).write({'active': False})
            template.write({
                'active': True,
                'name': _('׳תבנית ׳טופס 101'),
            })
            self._set_form_101_xmlid('sign_template_form_101', template)
            self.search([('sign_request_id', '=', False)]).write({
                'sign_template_id': template.id,
            })
            return template
        if template and template.sign_request_ids:
            # Reuse an existing request-free candidate when possible. This
            # prevents repeated upgrades from producing visible duplicates.
            new_template = (all_templates - template).filtered(
                lambda candidate: not candidate.sign_request_ids
                and candidate.document_ids[:1]
                and candidate.document_ids[:1].num_pages >= 2
            ).sorted('id', reverse=True)[:1]
            if not new_template:
                document = template.document_ids[:1]
                result = self.env['sign.template'].sudo().with_context(
                    default_model_name=self._name,
                ).create_from_attachment_data([{
                    'name': _('תבנית טופס 101'),
                    'datas': document.datas,
                }])
                new_template = self.env['sign.template'].sudo().browse(result['id'])
            new_template.write({
                'name': _('תבנית טופס 101'),
                'active': True,
                'model_id': form_model.id,
            })
            self._set_form_101_xmlid('sign_template_form_101', new_template)
            template = new_template
        else:
            template = template or self._ensure_form_101_sign_template()
        self._ensure_sign_template_configuration(template)
        other_templates = all_templates.filtered(lambda candidate: candidate != template)
        if other_templates:
            other_templates.write({'active': False})
        template.write({'active': True, 'name': _('תבנית טופס 101')})
        self.search([('sign_request_id', '=', False)]).write({
            'sign_template_id': template.id,
        })
        return template

    @api.model
    def _ensure_sign_template_configuration(self, template=None):
        template = template or self.env['sign.template'].browse(
            self._default_sign_template_id())
        if not template:
            return template
        document = template.document_ids[:1]
        if not document or document.num_pages < 2:
            raise ValidationError(_(
                'תבנית החתימה של טופס 101 חייבת להכיל את שני עמודי הטופס.'))
        # Never alter fields that already belong to signature requests. A
        # version migration creates a fresh template when a layout changes.
        if template.sign_request_ids:
            return template
        signature_item = document.sign_item_ids.filtered(
            lambda item: item.page == 2 and item.type_id.item_type == 'signature')[:1]
        form_model = self.env['ir.model']._get(self._name)
        if template.model_id != form_model:
            template.model_id = form_model

        employee_role = self.env.ref(
            'l10n_il_hr_payroll.sign_item_role_form_101_employee',
            raise_if_not_found=False,
        )
        if not employee_role:
            employee_role = signature_item.responsible_id if signature_item else False
        if not employee_role or employee_role.default:
            employee_role = self.env['sign.item.role'].sudo().create({
                'name': _('עובד/ת'),
            })
        elif employee_role.name != _('עובד/ת'):
            employee_role.sudo().write({'name': _('עובד/ת')})
        self._set_form_101_xmlid(
            'sign_item_role_form_101_employee', employee_role)

        signature_values = {
            'document_id': document.id,
            'type_id': self.env.ref('sign.sign_item_type_signature').id,
            'responsible_id': employee_role.id,
            'page': 2,
            'posX': 11.97 / 210,
            'posY': 226.017 / 297,
            'width': 31.08 / 210,
            'height': 5.346 / 297,
            'required': True,
            'constant': False,
            'alignment': 'center',
            'name': False,
        }
        if signature_item:
            signature_item.sudo().write(signature_values)
        else:
            signature_item = self.env['sign.item'].sudo().create(signature_values)

        # Once the canonical layer is installed, ordinary opens of the send
        # dialog must be read-only.  Rebuild only when the layout or types
        # actually differ (normally during a module upgrade).
        visible_items = document.sign_item_ids.filtered(
            lambda item: item.page in (1, 2))
        items_by_key = {
            definition['key']: item
            for item in visible_items
            if item != signature_item
            if (definition := _sign_definition_for_item(item))
        }
        configuration_matches = (
            len(visible_items) == len(_SIGN_TEMPLATE_ITEMS) + 1
            and len(items_by_key) == len(_SIGN_TEMPLATE_ITEMS)
            and all(
                items_by_key.get(definition['key'])
                and items_by_key[definition['key']].type_id == self.env.ref(
                    'sign.sign_item_type_radio'
                    if _SIGN_RADIO_GROUP_BY_KEY.get(definition['key'])
                    else definition['type_xmlid']
                )
                and items_by_key[definition['key']].responsible_id == employee_role
                and items_by_key[definition['key']].required == bool(
                    definition['auto_field']
                    and definition['auto_field'] in self._fields
                    and self._fields[definition['auto_field']].required
                )
                and not items_by_key[definition['key']].name
                and items_by_key[definition['key']].l10n_il_form_101_radio
                    == bool(_SIGN_RADIO_GROUP_BY_KEY.get(definition['key']))
                and abs(items_by_key[definition['key']].posX * 210
                        - definition['left']) <= 0.10
                and abs(items_by_key[definition['key']].posY * 297
                        - definition['top']) <= 0.10
                and abs(items_by_key[definition['key']].width * 210
                        - _sign_item_size(definition)[0]) <= 0.10
                and abs(items_by_key[definition['key']].height * 297
                        - _sign_item_size(definition)[1]) <= 0.10
                for definition in _SIGN_TEMPLATE_ITEMS
            )
        )
        if configuration_matches:
            for group in set(_SIGN_RADIO_GROUP_BY_KEY.values()):
                group_items = [
                    items_by_key[key]
                    for key, item_group in _SIGN_RADIO_GROUP_BY_KEY.items()
                    if item_group == group
                ]
                configuration_matches = bool(
                    group_items
                    and group_items[0].radio_set_id
                    and all(
                        item.radio_set_id == group_items[0].radio_set_id
                        for item in group_items
                    )
                )
                if not configuration_matches:
                    break
        if configuration_matches:
            return template

        # Rebuild the editable layer from the canonical coordinate map. This
        # guarantees that stale checkbox/text fields cannot survive upgrades.
        (document.sign_item_ids - signature_item).unlink()

        # Remove draft roles created by the Sign editor. Leaving those dummy
        # items would incorrectly add empty signers to the standard popup.
        document.sign_item_ids.filtered(lambda item: item.page < 0).unlink()

        item_model = self.env['sign.item'].sudo()
        radio_sets = {}
        for definition in _SIGN_TEMPLATE_ITEMS:
            radio_group = _SIGN_RADIO_GROUP_BY_KEY.get(definition['key'])
            type_xmlid = (
                'sign.sign_item_type_radio'
                if radio_group else definition['type_xmlid']
            )
            item_type = self.env.ref(type_xmlid)
            item_width, item_height = _sign_item_size(definition)
            values = {
                'document_id': document.id,
                'type_id': item_type.id,
                'responsible_id': employee_role.id,
                'page': definition['page'],
                'posX': definition['left'] / 210,
                'posY': definition['top'] / 297,
                'width': item_width / 210,
                'height': item_height / 297,
                # The employee fills these values in the native Sign screen.
                # Existing employee details are merely prefilled and remain
                # editable; the signature is validated separately below.
                'required': bool(
                    definition['auto_field']
                    and definition['auto_field'] in self._fields
                    and self._fields[definition['auto_field']].required
                ),
                'constant': False,
                'alignment': 'center',
                # Keep the box empty while signing. The business key is
                # resolved from the invisible auto_field on the item type.
                'name': False,
                'radio_set_id': False,
                'l10n_il_form_101_radio': bool(radio_group),
            }
            if radio_group:
                radio_set = radio_sets.get(radio_group)
                if not radio_set:
                    radio_set = self.env['sign.item.radio.set'].sudo().create({})
                    radio_sets[radio_group] = radio_set
                values['radio_set_id'] = radio_set.id
            item_model.create(values)
        return template

    @api.model
    def _is_form_101_sign_template(self, template):
        installed = self.env.ref(
            'l10n_il_hr_payroll.sign_template_form_101',
            raise_if_not_found=False,
        )
        return bool(template and installed and template == installed)

    @api.model
    def _employee_from_sign_request(self, request):
        reference = request.reference_doc
        if reference and reference._name == 'hr.employee.form.101':
            return reference.employee_id
        if reference and reference._name == 'hr.employee':
            return reference
        partners = request.request_item_ids.partner_id
        employees = self.env['hr.employee'].search([
            ('work_contact_id', 'in', partners.ids),
        ]) if partners else self.env['hr.employee']
        if len(employees) != 1:
            raise ValidationError(_(
                'כדי לשלוח טופס 101 יש לבחור איש קשר שמקושר לעובד אחד בדיוק.'))
        return employees

    @api.model
    def _sign_prefill_values(self, source):
        """Return editable native-Sign values from a form or an employee."""
        if source._name == 'hr.employee.form.101':
            form = source
        else:
            values = {'employee_id': source.id}
            values.update(self._employee_snapshot_values(source))
            values.setdefault('tax_year', str(fields.Date.context_today(self).year))
            form = self.new(values)
        result = {}
        for definition in _SIGN_TEMPLATE_ITEMS:
            field_name = definition['auto_field']
            if field_name not in form._fields:
                continue
            value = form[field_name]
            if hasattr(value, 'display_name'):
                value = value.display_name
            elif isinstance(value, bool):
                value = value and 'true' or ''
            elif isinstance(value, (fields.Date, fields.Datetime)):
                value = fields.Date.to_string(value)
            elif value is not False and value is not None:
                value = str(value)
            else:
                value = ''
            if value:
                result[definition['key']] = value
        return result

    @api.model
    def _prefill_sign_request(self, request, source):
        values_by_key = self._sign_prefill_values(source)
        for request_item in request.request_item_ids:
            sign_values = {}
            for item in request.template_id.sign_item_ids.filtered(
                    lambda sign_item: sign_item.responsible_id == request_item.role_id):
                # Values stored on a Sign request are rendered by Odoo as
                # completed, read-only controls.  Never prefill interactive
                # choices: every radio option and checkbox must remain a live
                # input that the employee can select while signing.
                if item.type_id.item_type in ('radio', 'checkbox'):
                    continue
                definition = _sign_definition_for_item(item)
                key = definition and definition['key']
                if not key:
                    continue
                value = values_by_key.get(key)
                if value not in (None, '', False):
                    sign_values[str(item.id)] = value
            if sign_values:
                request_item.sudo()._fill(sign_values)

    @api.model
    def _unlock_form_101_sign_choices(self):
        """Remove only generated choice prefills from unsigned requests."""
        template = self.env.ref(
            'l10n_il_hr_payroll.sign_template_form_101',
            raise_if_not_found=False,
        )
        if not template:
            return 0
        requests = self.env['sign.request'].sudo().search([
            ('template_id', '=', template.id),
            ('state', 'in', ('sent', 'shared')),
        ])
        values = requests.request_item_ids.sign_item_value_ids.filtered(
            lambda value: value.sign_item_id.type_id.item_type
            in ('radio', 'checkbox')
        )
        count = len(values)
        values.unlink()
        return count

    @api.model
    def _sign_request_value_map(self, request):
        result = {}
        for item_value in request.request_item_ids.sign_item_value_ids:
            definition = _sign_definition_for_item(item_value.sign_item_id)
            key = definition and definition['key']
            if key:
                result[key] = item_value.value
        return result

    @staticmethod
    def _sign_checked(value):
        return str(value or '').strip().lower() in {
            '1', 'true', 'on', 'yes', 'checked', 'x', 'v', '✓', '✔',
        }

    @api.model
    def _validate_sign_checkbox_values(self, raw):
        """Reject contradictory choices while keeping the legal square boxes."""
        exclusive_groups = [
            (_('מין'), ('sex_male', 'sex_female')),
            (_('מצב משפחתי'), (
                'marital_single', 'marital_married', 'marital_divorced',
                'marital_widower', 'marital_separated',
            )),
            (_('תושבות בישראל'), ('resident_yes', 'resident_no')),
            (_('חברות בקיבוץ או במושב שיתופי'), (
                'kibbutz_yes', 'kibbutz_no', 'kibbutz_not_transferred',
            )),
            (_('חברות בקופת חולים'), (
                'health_fund_yes', 'health_fund_no',
            )),
            (_('סוג ההכנסה מהמעסיק'), (
                'income_monthly', 'income_additional', 'income_partial',
                'income_daily', 'income_pension', 'income_scholarship',
            )),
            (_('הכנסות אחרות'), (
                'other_income_no', 'other_income_yes',
            )),
            (_('Spouse income'), (
                'spouse_no_income', 'spouse_has_income_yes',
            )),
            (_('נקודות זיכוי'), (
                'credit_points_here', 'credit_points_elsewhere',
            )),
            (_('סיבת תיאום מס'), (
                'tax_no_income', 'tax_additional_income', 'tax_officer',
            )),
        ]
        for label, keys in exclusive_groups:
            selected = [key for key in keys if self._sign_checked(raw.get(key))]
            if len(selected) > 1:
                raise ValidationError(_(
                    'בסעיף "%(section)s" ניתן לסמן אפשרות אחת בלבד.',
                    section=label,
                ))

        if self._sign_checked(raw.get('spouse_no_income')) and any(
                self._sign_checked(raw.get(key)) for key in (
                    'spouse_income_work', 'spouse_income_other')):
            raise ValidationError(_(
                'לא ניתן לסמן שלבן/בת הזוג אין הכנסה ובמקביל לסמן שיש לו/לה הכנסה.'))

        other_income_types = (
            'other_income_monthly', 'other_income_additional',
            'other_income_partial', 'other_income_daily',
            'other_income_pension', 'other_income_scholarship',
        )
        if self._sign_checked(raw.get('other_income_no')) and any(
                self._sign_checked(raw.get(key)) for key in other_income_types):
            raise ValidationError(_(
                'לא ניתן לסמן שאין הכנסות אחרות ובמקביל לבחור סוג של הכנסה אחרת.'))

        employer_income_types = (
            'income_monthly', 'income_additional', 'income_partial',
            'income_daily', 'income_pension', 'income_scholarship',
        )
        if not any(
                self._sign_checked(raw.get(key))
                for key in employer_income_types):
            raise ValidationError(_(
                'יש לבחור לפחות סוג הכנסה אחד מהמעסיק לפני החתימה.'))
        return True

    @api.model
    def _validate_sign_submission(self, request_item, signature):
        raw = self._sign_request_value_map(request_item.sign_request_id)
        if isinstance(signature, dict):
            for item_id, value in signature.items():
                try:
                    item = self.env['sign.item'].browse(int(item_id)).exists()
                except (TypeError, ValueError):
                    continue
                definition = item and _sign_definition_for_item(item)
                key = definition and definition['key']
                if key:
                    raw[key] = value
        return self._validate_sign_checkbox_values(raw)

    @api.model
    def _form_101_values_from_sign_request(self, request):
        """Translate the values entered on the legal PDF into a Form 101."""
        employee = self._employee_from_sign_request(request)
        raw = self._sign_request_value_map(request)
        self._validate_sign_checkbox_values(raw)
        values = self._employee_snapshot_values(employee)
        values['employee_id'] = employee.id

        direct_keys = {
            definition['key'] for definition in _SIGN_TEMPLATE_ITEMS
            if definition['key'] in self._fields
        }
        for key in direct_keys:
            raw_value = str(raw.get(key) or '').strip()
            if not raw_value:
                continue
            field = self._fields[key]
            if field.type == 'date':
                try:
                    values[key] = fields.Date.to_date(raw_value)
                except (TypeError, ValueError):
                    raise ValidationError(_('%(field)s חייב להיות תאריך תקין.', field=field.string))
            elif field.type == 'integer':
                try:
                    values[key] = int(float(raw_value))
                except ValueError:
                    raise ValidationError(_('%(field)s חייב להיות מספר.', field=field.string))
            elif field.type in ('float', 'monetary'):
                try:
                    values[key] = float(raw_value.replace(',', ''))
                except ValueError:
                    raise ValidationError(_('%(field)s חייב להיות מספר.', field=field.string))
            elif field.type not in ('boolean', 'binary', 'many2one', 'one2many', 'many2many'):
                values[key] = raw_value

        tax_year = str(raw.get('tax_year') or fields.Date.context_today(self).year).strip()
        if not (tax_year.isdigit() and len(tax_year) == 4
                and 1900 <= int(tax_year) <= 2200):
            raise ValidationError(_('שנת המס חייבת להכיל ארבע ספרות בין 1900 ל־2200.'))
        values['tax_year'] = tax_year

        def selected(prefix, choices):
            matches = [value for key, value in choices
                       if self._sign_checked(raw.get(f'{prefix}_{key}'))]
            return matches[-1] if matches else False

        values['sex'] = selected('sex', [('male', 'male'), ('female', 'female')]) or values.get('sex')
        values['marital'] = selected('marital', [(key, key) for key, __ in MARITAL_SELECTION]) or values.get('marital')
        values['is_israeli_resident'] = selected(
            'resident', [('yes', 'yes'), ('no', 'no')]) or values.get('is_israeli_resident')
        values['kibbutz_status'] = selected('kibbutz', [
            ('yes', 'income_transferred'), ('no', 'no'),
            ('not_transferred', 'income_not_transferred'),
        ]) or 'no'
        values['health_fund_member'] = selected(
            'health_fund', [('yes', 'yes'), ('no', 'no')])
        values['employer_income_main_type'] = selected('income', [
            ('monthly', 'monthly'), ('additional', 'additional'),
            ('partial', 'partial'), ('daily', 'daily'),
        ])
        values['employer_income_pension'] = self._sign_checked(raw.get('income_pension'))
        values['employer_income_scholarship'] = self._sign_checked(raw.get('income_scholarship'))
        values['has_other_income'] = selected(
            'other_income', [('no', 'no'), ('yes', 'yes')])
        values['credit_points_here'] = selected(
            'credit_points', [('here', 'here'), ('elsewhere', 'elsewhere')])
        values['spouse_has_income'] = (
            'yes' if self._sign_checked(raw.get('spouse_has_income_yes'))
            or any(self._sign_checked(raw.get(key)) for key in (
                'spouse_income_work', 'spouse_income_other'))
            else ('no' if self._sign_checked(raw.get('spouse_no_income')) else False)
        )

        boolean_keys = {
            'other_income_monthly', 'other_income_additional',
            'other_income_partial', 'other_income_daily',
            'other_income_pension', 'other_income_scholarship',
            'no_study_fund_elsewhere', 'no_pension_elsewhere',
            'spouse_income_work', 'spouse_income_other',
            'relief_resident', 'relief_disabled_blind',
            'relief_disabled_benefit', 'relief_eligible_settlement',
            'relief_new_immigrant', 'relief_spouse_no_income',
            'relief_single_parent_family', 'relief_children_in_custody',
            'relief_other_children', 'relief_single_parent',
            'relief_support_non_custody', 'relief_disabled_children',
            'relief_alimony_former_spouse', 'relief_age_16_18',
            'relief_discharged_service', 'relief_studies',
            'relief_reserve_combat',
        }
        for key in boolean_keys:
            values[key] = self._sign_checked(raw.get(key))

        tax_reason = selected('tax', [
            ('no_income', 'no_income'),
            ('additional_income', 'additional_income'),
            ('officer', 'tax_officer'),
        ])
        values['tax_coordination_requested'] = bool(tax_reason)
        values['tax_coordination_reason'] = tax_reason
        values['has_israeli_id'] = 'yes' if values.get('identification_id') else 'no'
        values['spouse_has_israeli_id'] = (
            'yes' if values.get('spouse_identification_id') else 'no')
        values['declaration_confirmed'] = True
        values['declaration_date'] = values.get('declaration_date') or fields.Date.context_today(self)
        values['state'] = 'signed'
        values['sign_request_id'] = request.id
        values['employee_signature'] = request.request_item_ids[:1].signature
        values['employee_signature_date'] = fields.Date.context_today(self)

        children = []
        for index in range(1, _SIGN_CHILD_ROW_COUNT + 1):
            name = str(raw.get(f'child_{index}_name') or '').strip()
            identity = str(raw.get(f'child_{index}_id') or '').strip()
            birthday = str(raw.get(f'child_{index}_birthday') or '').strip()
            if not any((name, identity, birthday)):
                continue
            if not all((name, identity, birthday)):
                raise ValidationError(_('יש למלא שם, מספר זהות ותאריך לידה לכל ילד.'))
            children.append(Command.create({
                'name': name,
                'identification_id': identity,
                'birthday': fields.Date.to_date(birthday),
                'in_custody': self._sign_checked(raw.get(f'child_{index}_custody')),
                'receives_child_allowance': self._sign_checked(raw.get(f'child_{index}_allowance')),
            }))
        values['child_ids'] = children

        income_type_by_label = {
            'work': 'work', 'עבודה': 'work',
            'pension': 'pension', 'קצבה': 'pension',
            'scholarship': 'scholarship', 'מלגה': 'scholarship',
            'other': 'other', 'אחר': 'other',
        }
        other_employers = []
        for index in range(1, 4):
            prefix = f'other_employer_{index}_'
            entered = {
                'name': str(raw.get(prefix + 'name') or '').strip(),
                'address': str(raw.get(prefix + 'address') or '').strip(),
                'withholding_file': str(raw.get(prefix + 'file') or '').strip(),
                'income_type': str(raw.get(prefix + 'type') or '').strip(),
                'monthly_income': str(raw.get(prefix + 'income') or '').strip(),
                'tax_withheld': str(raw.get(prefix + 'tax') or '').strip(),
            }
            if not any(entered.values()):
                continue
            if not all(entered.values()):
                raise ValidationError(_(
                    'יש למלא את כל הפרטים בכל שורה של מעסיק נוסף.'))
            income_type = income_type_by_label.get(entered['income_type'].lower())
            if not income_type:
                raise ValidationError(_(
                    'סוג ההכנסה אצל מעסיק נוסף חייב להיות עבודה, קצבה, מלגה או אחר.'))
            try:
                monthly_income = float(entered['monthly_income'].replace(',', ''))
                tax_withheld = float(entered['tax_withheld'].replace(',', ''))
            except ValueError:
                raise ValidationError(_(
                    'הכנסה חודשית ומס שנוכה אצל מעסיק נוסף חייבים להיות מספרים.'))
            other_employers.append(Command.create({
                'name': entered['name'],
                'address': entered['address'],
                'withholding_file': entered['withholding_file'],
                'income_type': income_type,
                'monthly_income': monthly_income,
                'tax_withheld': tax_withheld,
            }))
        values['other_employer_ids'] = other_employers
        return values

    @api.model
    def _create_from_sign_request(self, request):
        reference = request.reference_doc
        referenced_form = (
            reference
            if reference and reference._name == 'hr.employee.form.101'
            else self.env['hr.employee.form.101']
        )
        if referenced_form and (
                referenced_form.sign_request_id != request
                or referenced_form.state != 'sent'):
            # A request that was canceled or detached by "reset to draft"
            # must never be able to complete or recreate that old form.
            return referenced_form
        existing = referenced_form or self.search([
            ('sign_request_id', '=', request.id),
        ], limit=1)
        values = self._form_101_values_from_sign_request(request)
        completed = request.completed_document_ids[:1]
        if not completed or not completed.file:
            raise ValidationError(_('המסמך הושלם ללא קובץ חתום.'))
        values.update({
            'form_file': completed.file,
            'form_filename': _('טופס 101 חתום - %(employee)s - %(year)s.pdf',
                employee=self._employee_from_sign_request(request).name,
                year=values['tax_year']),
        })
        if existing:
            values['child_ids'] = [Command.clear(), *values.get('child_ids', [])]
            values['other_employer_ids'] = [
                Command.clear(), *values.get('other_employer_ids', [])]
            existing.with_context(
                skip_form_101_employee_sync=True,
                form_101_system_write=True,
            ).write(values)
            form = existing
        else:
            form = self.with_context(skip_form_101_employee_sync=True).create(values)
        form._validate_for_send()
        return form

    def action_confirm(self):
        return self.action_send_for_signature()

    def action_send_for_signature(self):
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError(_(
                'ניתן לשלוח לחתימה רק טופס 101 שנמצא במצב טיוטה.'))
        self._validate_for_send()
        partner = self.employee_id.work_contact_id
        if not partner or not partner.email:
            raise ValidationError(_(
                'לעובד חייב להיות איש קשר לעבודה עם כתובת דואר אלקטרוני.'))
        template = self._ensure_form_101_sign_template()
        return template.with_context(
            default_reference_doc=f'{self._name},{self.id}',
            default_signer_id=partner.id,
            default_form_101_employee_id=self.employee_id.id,
            default_model=self._name,
            default_res_ids=str(self.ids),
        ).open_sign_send_dialog()

    def action_open_sign_request(self):
        self.ensure_one()
        if not self.sign_request_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sign.request',
            'res_id': self.sign_request_id.id,
            'view_mode': 'form',
        }

    def action_activate(self):
        self.ensure_one()
        other_active = self.search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'active'),
            ('id', '!=', self.id),
        ], limit=1)
        if other_active and not self.env.context.get('form_101_replace_confirmed'):
            wizard = self.env['hr.employee.form.101.activation.wizard'].create({
                'form_id': self.id,
                'active_form_id': other_active.id,
            })
            return {
                'type': 'ir.actions.act_window',
                'name': _('החלפת טופס 101 פעיל'),
                'res_model': 'hr.employee.form.101.activation.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }
        if other_active:
            expected_active_id = self.env.context.get('expected_active_form_id')
            if expected_active_id and other_active.id != expected_active_id:
                raise ValidationError(_(
                    'הטופס הפעיל השתנה מאז פתיחת חלון האישור. יש לנסות שוב.'))
        self._validate_for_activation()
        if other_active:
            other_active._reset_to_draft(cancel_pending_request=False)
        self._apply_to_employee_if_needed()
        self.with_context(skip_form_101_employee_sync=True).write({'state': 'active'})
        return True

    def _validate_for_send(self):
        for form in self:
            missing = []
            for field_name, label in (
                ('employer_name', _('שם המעסיק')),
                ('employer_address', _('כתובת המעסיק')),
                ('employer_phone', _('טלפון המעסיק')),
                ('employer_withholding_file', _('מספר תיק ניכויים')),
                ('first_name', _('שם פרטי')),
                ('birthday', _('תאריך לידה')),
                ('private_street', _('רחוב / שכונה')),
                ('private_house_number', _('מספר בית')),
                ('private_city', _('עיר / יישוב')),
                ('sex', _('מין')),
                ('marital', _('מצב משפחתי')),
                ('employment_start_date', _('תאריך תחילת העבודה בשנת המס')),
                ('has_other_income', _('הכנסות אחרות')),
            ):
                if not form[field_name]:
                    missing.append(label)
            if not form.private_phone and not form.mobile_phone:
                missing.append(_('מספר טלפון או מספר טלפון נייד'))
            if not (form.employer_income_main_type or form.employer_income_pension
                    or form.employer_income_scholarship):
                missing.append(_('סוג הכנסה ממעסיק זה'))
            if not form.declaration_confirmed:
                missing.append(_('אישור הצהרת העובד'))
            if not form.declaration_date:
                missing.append(_('תאריך ההצהרה'))
            if missing:
                raise ValidationError(_('לא ניתן לשלוח את הטופס. חסרים שדות חובה: %s',
                                        ', '.join(missing)))
            if form.has_israeli_id == 'yes' and not form.identification_id:
                raise ValidationError(_('יש להזין מספר תעודת זהות.'))
            if form.has_israeli_id == 'no' and not form.passport_id:
                raise ValidationError(_('יש להזין מספר דרכון לעובד ללא תעודת זהות.'))
            if form.health_fund_member == 'yes' and not form.health_fund_name:
                raise ValidationError(_('יש להזין את שם קופת החולים.'))
            if form.marital == 'married':
                if not form.spouse_first_name or not form.spouse_last_name:
                    raise ValidationError(_('בטופס של עובד/ת נשוי/אה יש למלא את שם בן/בת הזוג.'))
                if form.spouse_has_israeli_id == 'yes' and not form.spouse_identification_id:
                    raise ValidationError(_('יש להזין מספר זהות של בן/בת הזוג.'))
                if form.spouse_has_israeli_id == 'no' and not form.spouse_passport_id:
                    raise ValidationError(_('יש להזין מספר דרכון של בן/בת הזוג.'))
                if not form.spouse_birthdate or not form.spouse_has_income:
                    raise ValidationError(_(
                        'בטופס של עובד/ת נשוי/אה יש למלא תאריך לידה והכנסה של בן/בת הזוג.'))
            if form.has_other_income == 'yes' and not any((
                    form.other_income_monthly, form.other_income_additional,
                    form.other_income_partial, form.other_income_daily,
                    form.other_income_pension, form.other_income_scholarship)):
                raise ValidationError(_('יש לבחור לפחות סוג אחד של הכנסה אחרת.'))

    def _validate_for_activation(self):
        self._validate_for_send()
        for form in self:
            if form.state != 'signed' or not form.form_file:
                raise ValidationError(_(
                    'ניתן להפוך לפעיל רק טופס שנחתם ונוצר עבורו קובץ חתום.'))

    def _reset_to_draft(self, cancel_pending_request=True):
        for form in self:
            request = form.sign_request_id
            if (cancel_pending_request and request
                    and request.state not in ('signed', 'canceled', 'expired')):
                request.cancel()
            form.with_context(skip_form_101_employee_sync=True).write({
                'state': 'draft',
                'sign_request_id': False,
                'form_file': False,
                'form_filename': False,
                'employee_signature': False,
                'employee_signature_date': False,
            })

    def action_reset_to_draft(self):
        self._reset_to_draft()
        return True

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'l10n_il_hr_payroll.action_report_employee_form_101'
        ).report_action(self, config=False)

    @api.constrains('private_phone', 'mobile_phone')
    def _check_phone(self):
        for form in self:
            if not form.private_phone and not form.mobile_phone:
                raise ValidationError(_('יש להזין מספר טלפון או מספר טלפון נייד.'))

    @api.constrains('employer_income_main_type', 'employer_income_pension',
                    'employer_income_scholarship')
    def _check_employer_income_type(self):
        for form in self:
            if not (form.employer_income_main_type or form.employer_income_pension
                    or form.employer_income_scholarship):
                raise ValidationError(_('יש לבחור לפחות סוג הכנסה אחד ממעסיק זה.'))

    @api.constrains('declaration_confirmed')
    def _check_declaration_confirmed(self):
        for form in self:
            if not form.declaration_confirmed:
                raise ValidationError(_('חובה לאשר את הצהרת העובד.'))

    @api.constrains('has_israeli_id', 'identification_id', 'passport_id')
    def _check_identity_document(self):
        for form in self:
            if form.has_israeli_id == 'yes' and not form.identification_id:
                raise ValidationError(_('יש להזין מספר תעודת זהות.'))
            if form.has_israeli_id == 'no' and not form.passport_id:
                raise ValidationError(_('יש להזין מספר דרכון לעובד ללא תעודת זהות.'))

    @api.constrains('health_fund_member', 'health_fund_name')
    def _check_health_fund(self):
        for form in self:
            if form.health_fund_member == 'yes' and not form.health_fund_name:
                raise ValidationError(_('יש להזין את שם קופת החולים.'))

    @api.constrains('marital', 'spouse_has_israeli_id', 'spouse_identification_id',
                    'spouse_passport_id', 'spouse_first_name', 'spouse_last_name',
                    'spouse_birthdate', 'spouse_has_income')
    def _check_required_spouse_details(self):
        for form in self.filtered(lambda item: item.marital == 'married'):
            if not all((form.spouse_first_name, form.spouse_last_name,
                        form.spouse_birthdate, form.spouse_has_income)):
                raise ValidationError(_('יש למלא את כל פרטי בן/בת הזוג.'))
            if form.spouse_has_israeli_id == 'yes' and not form.spouse_identification_id:
                raise ValidationError(_('יש להזין מספר זהות של בן/בת הזוג.'))
            if form.spouse_has_israeli_id == 'no' and not form.spouse_passport_id:
                raise ValidationError(_('יש להזין מספר דרכון של בן/בת הזוג.'))

    @api.constrains('has_other_income', 'other_income_monthly', 'other_income_additional',
                    'other_income_partial', 'other_income_daily', 'other_income_pension',
                    'other_income_scholarship')
    def _check_other_income_type(self):
        for form in self.filtered(lambda item: item.has_other_income == 'yes'):
            if not any((form.other_income_monthly, form.other_income_additional,
                        form.other_income_partial, form.other_income_daily,
                        form.other_income_pension, form.other_income_scholarship)):
                raise ValidationError(_('יש לבחור לפחות סוג אחד של הכנסה אחרת.'))

class HrEmployeeForm101Child(models.Model):
    _name = 'hr.employee.form.101.child'
    _description = 'ילד בטופס 101'
    _order = 'birthday, id'

    form_id = fields.Many2one('hr.employee.form.101', required=True, ondelete='cascade')
    name = fields.Char(string='שם', required=True)
    identification_id = fields.Char(string='מספר זהות', required=True)
    birthday = fields.Date(string='תאריך לידה', required=True)
    in_custody = fields.Boolean(string='הילד בחזקתי')
    receives_child_allowance = fields.Boolean(string='מקבל/ת קצבת ילדים')

    @api.constrains('birthday', 'form_id.tax_year')
    def _check_age(self):
        for child in self.filtered('birthday'):
            if int(child.form_id.tax_year) - child.birthday.year >= 19:
                raise ValidationError(_('בחלק ג׳ ניתן לרשום רק ילדים שטרם מלאו להם 19 בשנת המס.'))


class HrEmployeeForm101OtherEmployer(models.Model):
    _name = 'hr.employee.form.101.other.employer'
    _description = 'מעסיק נוסף בטופס 101'

    form_id = fields.Many2one('hr.employee.form.101', required=True, ondelete='cascade')
    name = fields.Char(string='שם המעסיק / המשלם', required=True)
    address = fields.Char(string='כתובת', required=True)
    withholding_file = fields.Char(string='מספר תיק ניכויים', required=True)
    income_type = fields.Selection(
        [('work', 'עבודה'), ('pension', 'קצבה'), ('scholarship', 'מלגה'), ('other', 'אחר')],
        string='סוג הכנסה', required=True)
    monthly_income = fields.Monetary(string='הכנסה חודשית', required=True)
    tax_withheld = fields.Monetary(string='מס שנוכה', required=True)
    payslip_file = fields.Binary(
        string='צילום תלוש שכר', attachment=True, copy=False)
    currency_id = fields.Many2one(
        'res.currency', related='form_id.company_id.currency_id', readonly=True)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    form_101_ids = fields.One2many(
        'hr.employee.form.101', 'employee_id', string='טפסי 101')
    form_101_count = fields.Integer(compute='_compute_form_101_count')

    def _compute_form_101_count(self):
        grouped = self.env['hr.employee.form.101']._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count'])
        counts = {employee.id: count for employee, count in grouped}
        for employee in self:
            employee.form_101_count = counts.get(employee.id, 0)

    def action_open_form_101(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'l10n_il_hr_payroll.action_hr_employee_form_101')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'default_employee_id': self.id}
        return action

    def action_send_form_101_for_completion(self):
        self.ensure_one()
        partner = self.work_contact_id
        if not partner or not partner.email:
            raise ValidationError(_(
                'לעובד חייב להיות איש קשר לעבודה עם כתובת דואר אלקטרוני.'))
        form_model = self.env['hr.employee.form.101']
        template = form_model._ensure_form_101_sign_template()
        return template.with_context(
            default_reference_doc=f'{self._name},{self.id}',
            default_signer_id=partner.id,
            default_form_101_employee_id=self.id,
            default_model=self._name,
            default_res_ids=str(self.ids),
        ).open_sign_send_dialog()
