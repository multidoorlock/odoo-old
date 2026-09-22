import subprocess
import tempfile
from pathlib import Path

import pymupdf


TESSERACT = Path('tmp/tesseract-unpacked/tesseract.exe').resolve()
TESSDATA = Path('tmp/tesseract-unpacked/tessdata').resolve()


def ocr_page(page, scale=3.2):
    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / 'page.png'
        page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(image)
        result = subprocess.run(
            [str(TESSERACT), str(image), 'stdout', '--tessdata-dir', str(TESSDATA),
             '-l', 'heb+eng', '--psm', '6'],
            check=True, capture_output=True)
        return result.stdout.decode('utf-8', errors='replace')


if __name__ == '__main__':
    source = next(Path('tmp/form101_import').rglob('אגם אשר*.pdf'))
    document = pymupdf.open(source)
    print(ocr_page(document[0]).encode('unicode_escape').decode())
