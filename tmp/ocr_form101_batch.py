import hashlib
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf


ROOT = Path('tmp/form101_import')
OUTPUT = Path('tmp/form101_ocr.json')
TESSERACT = Path('tmp/tesseract-unpacked/tesseract.exe').resolve()
TESSDATA = Path('tmp/tesseract-unpacked/tessdata').resolve()


def extract(path):
    raw = path.read_bytes()
    document = pymupdf.open(stream=raw, filetype='pdf')
    pages = []
    for page_number in range(min(2, document.page_count)):
        page = document[page_number]
        embedded = page.get_text().strip()
        # OCR remains authoritative for the scanned handwritten forms.  Keep
        # embedded text as an additional source when the PDF contains it.
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'page.png'
            page.get_pixmap(matrix=pymupdf.Matrix(2.5, 2.5), alpha=False).save(image)
            result = subprocess.run(
                [str(TESSERACT), str(image), 'stdout', '--tessdata-dir', str(TESSDATA),
                 '-l', 'heb+eng', '--psm', '6'],
                check=True, capture_output=True,
            )
        pages.append({
            'page': page_number + 1,
            'embedded': embedded,
            'ocr': result.stdout.decode('utf-8', errors='replace'),
        })
    return {
        'path': str(path.resolve()),
        'name': path.name,
        'sha256': hashlib.sha256(raw).hexdigest(),
        'page_count': document.page_count,
        'pages': pages,
    }


paths = sorted(
    path for path in ROOT.rglob('*.pdf')
    if 'טופס 101' in path.name or 'טופס 101' in str(path.parent)
)
results = []
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(extract, path): path for path in paths}
    for completed, future in enumerate(as_completed(futures), 1):
        results.append(future.result())
        print(f'OCR {completed}/{len(paths)}', flush=True)

results.sort(key=lambda item: item['name'])
OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print({'files': len(results), 'unique': len({item['sha256'] for item in results})})
