import json
import re


items = json.load(open('tmp/form101_ocr.json', encoding='utf-8'))
for item in items:
    text = '\n'.join(page['ocr'] for page in item['pages'])
    identifiers = sorted(set(re.findall(r'(?<!\d)\d(?:[\s.\-]?\d){8}(?!\d)', text)))
    identifiers = [''.join(re.findall(r'\d', value)) for value in identifiers]
    dates = sorted(set(re.findall(r'(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)?\d{2}(?!\d)', text)))
    years = sorted(set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', text)))
    print(item['name'])
    print('  pages=', item['page_count'], 'ids=', identifiers, 'dates=', dates, 'years=', years)
