import collections
import json


results = json.load(open('tmp/pdfs/audit_result.json', encoding='utf8'))['results']
groups = collections.defaultdict(list)
for item in results:
    groups[item['identification_id']].append(item)
for identification_id, items in sorted(
        groups.items(), key=lambda pair: max(abs(item['net_error']) for item in pair[1]),
        reverse=True):
    print(
        identification_id,
        items[0]['employee_name'].encode('unicode_escape').decode(),
        [(item['file'][-2:], item['net_error'], item['errors']['income_tax'],
          item['errors']['pension'], item['credit_points']) for item in items],
    )
