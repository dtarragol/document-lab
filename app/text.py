"""Extracción local acotada; nunca ejecuta macros ni instrucciones del documento."""
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree


class TextError(ValueError):
    pass


def extract_text(path: Path, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    try:
        if extension == '.txt':
            text = path.read_text(encoding='utf-8-sig')
        elif extension == '.docx':
            with ZipFile(path) as archive:
                entry = archive.getinfo('word/document.xml')
                if entry.file_size > 4 * 1024 * 1024:
                    raise TextError('El XML del DOCX supera 4 MiB')
                xml = archive.read(entry)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise TextError('XML con declaraciones no admitidas')
            root = ElementTree.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text = '\n'.join(''.join(node.itertext()) for node in root.findall('.//w:p', ns)
                             if node is not None)
        else:
            raise TextError('Extracción disponible solo para TXT UTF-8 y DOCX')
    except (UnicodeError, BadZipFile, KeyError, ElementTree.ParseError, OSError) as error:
        raise TextError('No se puede leer el documento como TXT UTF-8 o DOCX válido') from error
    if not text.strip():
        raise TextError('El documento no contiene texto extraíble')
    return text


def analyze_text(text: str) -> dict:
    return dict(category='invoice' if any(w in text.lower() for w in ('factura', 'invoice')) else 'other',
                confidence=0.72, requires_review=True, simulated=True)
