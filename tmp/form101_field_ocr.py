import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf


TESSERACT = Path('tmp/tesseract-unpacked/tesseract.exe').resolve()
TESSDATA = Path('tmp/tesseract-unpacked/tessdata').resolve()
ITEMS = json.load(open('tmp/form101_ocr.json', encoding='utf-8'))
OUTPUT = Path('tmp/form101_field_ocr.json')


def run_ocr(pixmap, directory, key, language='heb+eng', whitelist=None):
    image = Path(directory) / f'{key}.png'
    pixmap.save(image)
    command = [str(TESSERACT), str(image), 'stdout', '--tessdata-dir', str(TESSDATA),
               '-l', language, '--psm', '11']
    if whitelist:
        command.extend(['-c', f'tessedit_char_whitelist={whitelist}'])
    result = subprocess.run(command, check=True, capture_output=True)
    return result.stdout.decode('utf-8', errors='replace').strip()


def extract(item):
    document = pymupdf.open(item['path'])
    page = document[0]
    width, height = page.rect.width, page.rect.height
    matrix = pymupdf.Matrix(4, 4)
    areas = {
        'tax_year': (0.28, 0.07, 0.72, 0.18),
        'identity': (0.62, 0.18, 0.99, 0.34),
        'personal': (0.01, 0.17, 0.99, 0.42),
        'income': (0.01, 0.40, 0.99, 0.67),
    }
    result = {'name': item['name'], 'path': item['path']}
    with tempfile.TemporaryDirectory() as directory:
        for key, fractions in areas.items():
            x0, y0, x1, y1 = fractions
            pixmap = page.get_pixmap(
                matrix=matrix,
                clip=pymupdf.Rect(x0 * width, y0 * height, x1 * width, y1 * height),
                alpha=False,
            )
            if key == 'tax_year':
                result[key] = run_ocr(pixmap, directory, key, language='eng', whitelist='0123456789./-')
            else:
                result[key] = run_ocr(pixmap, directory, key)
    return result


results = []
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(extract, item) for item in ITEMS]
    for index, future in enumerate(as_completed(futures), 1):
        results.append(future.result())
        print(f'FIELDS {index}/{len(futures)}', flush=True)
results.sort(key=lambda item: item['name'])
OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
