import json
import re
from pathlib import Path

import pymupdf


downloads = Path(r"C:\Users\ItayYosef\Downloads")
documents = Path(r"C:\Users\ItayYosef\OneDrive - Multi DoorLock LTD\Documents\PDF Documents")
FILES = [
    ('multi_2026_04', next(downloads.glob('*4.2026.pdf')), 'multi'),
    ('multi_2026_06', next(downloads.glob('*6.2026.pdf')), 'scan'),
    ('multi_2026_03', next(downloads.glob('*03-26*.pdf')), 'multi'),
    ('multi_2026_05', next(downloads.glob('*05-26*.pdf')), 'multi'),
]
for month in range(2, 9):
    FILES.append((
        f'autonomy_2026_{month:02d}',
        next(documents.glob(f'*{month:02d}-26*.pdf')),
        'autonomy'))

JUNE = [
    (22585,16000,[3245,1122,1018,1200],2.25,22585,135514.16,[19472.16,6731,6111,7200],('income_tax','national_insurance','health_insurance','pension')),
    (19780,15000,[2415.2,926,873,565.8],2.25,19780,118678.77,[14490.97,5553,5240,3394.8],('income_tax','national_insurance','health_insurance','pension')),
    (10807.85,9000,[535.05,298,409,565.8],2.25,10807.85,64847.07,[3210.27,1788,2454,3394.8],('income_tax','national_insurance','health_insurance','pension')),
    (10885.3,8800,[707.5,358,454,565.8],2.25,11670.83,67913.01,[3823.68,2000,2614,3394.8],('income_tax','national_insurance','health_insurance','pension')),
    (10629.08,9000,[378.28,285,400,565.8],2.75,10629.08,62130.22,[1954.57,1594,2316,3355.65],('income_tax','national_insurance','health_insurance','pension')),
    (24123,19000,[2230.2,1229,1098,565.8],6.25,24123,109357.51,[6304.71,4902,4756,3394.8],('income_tax','national_insurance','health_insurance','pension')),
    (12076.76,9870,[734.76,375,467,630],2.25,11919.26,72688.11,[4643.81,2333,2862,3780],('income_tax','national_insurance','health_insurance','pension')),
    (13539,11280,[522,476,541,720],4.25,13359,85258.33,[4151.13,3213,3511,4320],('income_tax','national_insurance','health_insurance','pension')),
    (8455,7520,[174,281,480],2.25,8335,53488.25,[1531.45,1868,2880],('income_tax','health_insurance','pension')),
    (9913,8000,[241,686,506,480],2.75,9793,62922.25,[2279.45,4407,3252,2880],('income_tax','national_insurance','health_insurance','pension')),
    (14173,11500,[888,521,574,690],3.25,14000.5,79616.26,[4577.26,2820,3218,3780],('income_tax','national_insurance','health_insurance','pension')),
    (1045.2,1000,[11,34,.2],2.75,1045.2,5225.88,[55,170],('national_insurance','health_insurance','rounding')),
    (9992,8460,[385,240,367,540],2.25,9992,33789.49,[1242.25,699,1204,540],('income_tax','national_insurance','health_insurance','pension')),
    (499.98,484,[16,-.02],2.25,499.98,1583.96,[51],('health_insurance','rounding')),
    (8985,8500,[170,315],2.25,8985,17970,[340,630],('national_insurance','health_insurance')),
    (2045.46,1958,[21,66,.46],2.75,2045.46,2045.46,[21,66],('national_insurance','health_insurance','rounding')),
]

JUNE_NAMES = [
    'חסון יוסף', 'מיודובניק עמית', 'עומר עומר', 'בשארי אורי',
    'עווידה נורין', 'אשר אורן', 'צוברי שחר', 'עמרן אמיר',
    'אבשלום דניאל', 'עמרם אגם', 'סטלובסקי אפרת', 'אשר טוהר',
    'קוצר אוהד יצחק', 'פלקה באסופקד', 'אשר אגם', 'דאסה סול קורן',
]

JUNE_IDS = [
    '059630210', '027464163', '326356482', '315115451',
    '318448826', '060462561', '025343559', '060716081',
    '318956539', '326453933', '027173723', '331096776',
    '325019487', '313594277', '326371572', '327937686',
]

AMOUNT = re.compile(r'(?<![\d.])(-?\d[\d,]*\.\d{2})(?!\d)')


def vals(line):
    return [float(value.replace(',', '')) for value in AMOUNT.findall(line)]


def suffix(entries, total):
    picked = []
    for entry in reversed(entries):
        picked.insert(0, entry)
        if abs(sum(item[0] for item in picked) - total) <= .02:
            return picked
    return []


def digits(value):
    return ''.join(character for character in value if character.isdigit())


def multi_identity(lines):
    employee_name = ''
    try:
        employee_name = lines[lines.index('לכבוד') + 1]
    except (ValueError, IndexError):
        pass
    identification_id = ''
    for line in lines:
        if 'מספר זהות' not in line:
            continue
        candidates = re.findall(r'\d{7,9}', line)
        if candidates:
            identification_id = candidates[0].zfill(9)
            break
    return employee_name, identification_id


def autonomy_identity(lines):
    employee_name = lines[2] if len(lines) > 2 else ''
    identification_id = ''
    for line in lines[3:16]:
        value = digits(line)
        if len(value) == 9 and '-' in line:
            identification_id = value
            break
    return employee_name, identification_id


def component(label):
    if 'מס הכנסה' in label: return 'income_tax'
    if 'ב.לאומי' in label: return 'national_insurance'
    if 'מס בריאות' in label: return 'health_insurance'
    if any(value in label for value in ('פנסיה', 'גמל', 'לביטוח')): return 'pension'
    return 'rounding'


def parse_multi(text, key, page):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    employee_name, identification_id = multi_identity(lines)
    occurrences = [(index, value) for index, line in enumerate(lines) for value in vals(line)]
    to_pay = occurrences[-1][1]
    marker = next((i for i, line in enumerate(lines) if '8.27' in line), len(lines))
    candidates = []
    for net_pos, net in occurrences:
        if net_pos >= marker: continue
        for total_pos, total in occurrences:
            if total_pos >= net_pos: continue
            for gross_pos, gross in occurrences:
                if total_pos < gross_pos < net_pos and abs(gross - net - total) <= .02 and gross > 0:
                    candidates.append((net, gross, net_pos, gross_pos, total_pos, total))
    net, gross, net_pos, gross_pos, total_pos, total = max(candidates, key=lambda item: (item[0], item[1]))
    entries = []
    for line in lines[max(0, total_pos - 12):total_pos]:
        entries.extend((value, AMOUNT.sub('', line).strip()) for value in vals(line))
    deductions = suffix(entries, total)
    components = {}
    for value, label in deductions:
        name = component(label)
        components[name] = round(components.get(name, 0) + value, 2)
    points = None
    for line in lines[marker + 1:marker + 4]:
        if vals(line): points = vals(line)[-1]; break
    after = [value for index, value in occurrences if index > marker]
    duplicates = []
    for index, value in enumerate(after):
        if value < max(gross * .5, 100): continue
        for second in range(index + 1, min(index + 4, len(after))):
            if abs(value - after[second]) <= .02:
                duplicates.append((index, second, value)); break
    current_base = duplicates[0][2] if duplicates else gross
    _first, second, ytd_base = max(duplicates, key=lambda item: (item[2], item[0]), default=(None,None,current_base))
    order = [name for name in ('income_tax','national_insurance','health_insurance','pension') if name in components]
    ytd_values = after[second + 1:second + 1 + len(order)] if second is not None else []
    if not ytd_values and abs(ytd_base-current_base)<=.02:
        ytd_values = [components[name] for name in order]
    return {'file':key,'page':page,'layout':'multi','employee_name':employee_name,'identification_id':identification_id,'gross':round(gross,2),'net':round(net,2),'to_pay':round(to_pay,2),'payments':round(net-to_pay,2),'components':components,'credit_points':points,'current_tax_base':round(current_base,2),'ytd_tax_base':round(ytd_base,2),'ytd_components':dict(zip(order,ytd_values))}


def parse_autonomy(text, key, page):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    employee_name, identification_id = autonomy_identity(lines)
    occurrences = [(index, values[0]) for index, line in enumerate(lines) if len((values:=vals(line)))==1 and AMOUNT.fullmatch(line)]
    match = None
    for offset in range(len(occurrences)-2):
        a, b, c = occurrences[offset:offset+3]
        if abs(a[1]-b[1]-c[1])<=.02:
            match=(offset,c[1],b[1],a[1]); break
    offset, net, total, gross = match
    pos = occurrences[offset][0]
    entries=[]
    for line in lines[max(0,pos-12):pos]: entries.extend((value,AMOUNT.sub('',line).strip()) for value in vals(line))
    deductions=[value for value,_label in suffix(entries,total)]
    components={}
    if deductions: components['income_tax']=deductions[0]
    if len(deductions)>1: components['national_insurance']=deductions[1]
    tail=[value for _index,value in occurrences[offset+3:]]
    current_base=tail[0] if tail else gross
    ytd_base=tail[1] if len(tail)>1 else current_base
    ytd=(tail[6:8] if len(tail)>7 else deductions)
    marital=next((i for i,line in enumerate(lines) if 'נשוי/אה' in line),None)
    points=1.0
    if marital is not None:
        for line in lines[marital+1:marital+6]:
            if vals(line): points=vals(line)[0]; break
    return {'file':key,'page':page,'layout':'autonomy','employee_name':employee_name,'identification_id':identification_id,'gross':round(gross,2),'net':round(net,2),'to_pay':round(net,2),'payments':0.0,'components':components,'credit_points':points,'current_tax_base':current_base,'ytd_tax_base':ytd_base,'ytd_components':dict(zip(('income_tax','national_insurance'),ytd))}


def parse_autonomy_coordinates(pdf_page, key, page):
    """Parse the fixed payslip boxes by geometry, not text reading order."""
    text = pdf_page.get_text()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    employee_name, identification_id = autonomy_identity(lines)
    width, height = pdf_page.rect.width, pdf_page.rect.height
    amount_words = []
    for word in pdf_page.get_text('words'):
        match = AMOUNT.fullmatch(word[4])
        if match:
            amount_words.append((
                (word[0] + word[2]) / 2 / width,
                (word[1] + word[3]) / 2 / height,
                float(match.group(1).replace(',', '')),
            ))

    def amount_in(x1, x2, y1, y2, default=0.0):
        matches = [
            value for x, y, value in amount_words
            if x1 <= x <= x2 and y1 <= y <= y2
        ]
        return matches[0] if matches else default

    gross = amount_in(.02, .15, .490, .515)
    total = amount_in(.02, .15, .515, .535)
    net = amount_in(.02, .15, .530, .550)
    payments = amount_in(.02, .15, .545, .565)
    to_pay = amount_in(.02, .15, .558, .582, net - payments)
    deductions = [
        value for x, y, value in amount_words
        if .02 <= x <= .15 and .180 <= y <= .235
    ]
    components = {}
    if deductions:
        components['income_tax'] = deductions[0]
    if len(deductions) > 1:
        components['national_insurance'] = deductions[1]
    current_base = amount_in(.72, .84, .600, .635, gross)
    ytd_base = amount_in(.61, .72, .600, .635, current_base)
    ytd = [
        value for x, y, value in amount_words
        if .40 <= x <= .50 and .600 <= y <= .650
    ][:2] or deductions
    points = amount_in(.42, .52, .720, .770, 1.0)
    return {
        'file': key, 'page': page, 'layout': 'autonomy',
        'employee_name': employee_name,
        'identification_id': identification_id,
        'gross': round(gross, 2), 'net': round(net, 2),
        'to_pay': round(to_pay, 2), 'payments': round(payments, 2),
        'components': components, 'credit_points': points,
        'current_tax_base': current_base, 'ytd_tax_base': ytd_base,
        'ytd_components': dict(zip(('income_tax', 'national_insurance'), ytd)),
    }


rows=[]
for key,path,layout in FILES:
    doc=pymupdf.open(path)
    for page,pdf_page in enumerate(doc,1):
        if layout=='multi': row=parse_multi(pdf_page.get_text(),key,page)
        elif layout=='autonomy': row=parse_autonomy_coordinates(pdf_page,key,page)
        else:
            gross,net,deductions,points,current,ytd,ytd_values,order=JUNE[page-1]
            row={'file':key,'page':page,'layout':'multi','employee_name':JUNE_NAMES[page-1],'identification_id':JUNE_IDS[page-1],'gross':gross,'net':net,'to_pay':net,'payments':0.0,'components':dict(zip(order,deductions)),'credit_points':points,'current_tax_base':current,'ytd_tax_base':ytd,'ytd_components':dict(zip([name for name in order if name!='rounding'],ytd_values))}
        rows.append(row)

identification_by_name = {
    row['employee_name']: row['identification_id'] for row in rows
    if row.get('employee_name') and row.get('identification_id')
}
for row in rows:
    if not row.get('identification_id'):
        row['identification_id'] = identification_by_name.get(row.get('employee_name'), '')

# Two Autonomia August pages contain a separate advance/payment after NET.
for row in rows:
    if row['file']=='autonomy_2026_08' and row['page'] in (16,18):
        row['payments']=2000.0
        row['to_pay']=row['net']-2000.0

Path('tmp/pdfs/audit_source.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
print({'total':len(rows),'by_layout':{name:sum(r['layout']==name for r in rows) for name in ('multi','autonomy')}})
