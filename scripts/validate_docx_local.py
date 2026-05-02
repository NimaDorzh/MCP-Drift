from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


REQUIRED_MEMBERS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "docProps/core.xml",
    "word/document.xml",
    "word/styles.xml",
}


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if len(args) != 1:
        print("usage: validate_docx_local.py <docx_path>")
        return 2

    docx_path = Path(args[0])
    if not docx_path.exists():
      print(f"ERROR: file not found: {docx_path}")
      return 1

    errors: list[str] = []
    try:
        with zipfile.ZipFile(docx_path) as archive:
            members = set(archive.namelist())
            for member in sorted(REQUIRED_MEMBERS - members):
                errors.append(f"missing zip member: {member}")

            if "word/document.xml" in members:
                document_xml = archive.read("word/document.xml")
                try:
                    root = ET.fromstring(document_xml)
                except ET.ParseError as exc:
                    errors.append(f"invalid word/document.xml: {exc}")
                else:
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    paragraphs = root.findall(".//w:p", ns)
                    if not paragraphs:
                        errors.append("document.xml contains no paragraphs")
                    if b"MCPDrift: Security Benchmark Analysis" not in document_xml:
                        errors.append("title text not found in document.xml")
    except zipfile.BadZipFile as exc:
        errors.append(f"invalid zip/docx container: {exc}")

    if errors:
        print("Validation failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Validation passed with 0 errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())