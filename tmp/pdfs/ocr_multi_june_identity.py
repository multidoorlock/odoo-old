import json
import subprocess
import tempfile
from pathlib import Path

import pymupdf


source = next(Path(r'C:\Users\ItayYosef\Downloads').glob('*6.2026.pdf'))
tesseract = Path('tmp/tesseract-unpacked/tesseract.exe').resolve()
tessdata = Path('tmp/tesseract-unpacked/tessdata').resolve()
document = pymupdf.open(source)
results = []
with tempfile.TemporaryDirectory() as directory:
    for index, page in enumerate(document, 1):
        clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.30)
        image = Path(directory) / f'{index:02d}.png'
        page.get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=clip, alpha=False).save(image)
        output = subprocess.run(
            [str(tesseract), str(image), 'stdout', '--tessdata-dir', str(tessdata),
             '-l', 'heb+eng', '--psm', '6'],
            check=True, capture_output=True,
        ).stdout.decode('utf-8', errors='replace')
        results.append({'page': index, 'ocr': output})
        print(index, output.replace('\n', ' | '), flush=True)
Path('tmp/pdfs/multi_june_identity.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
