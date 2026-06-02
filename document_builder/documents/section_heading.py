from docx.document import Document as DocumentType
from docx.shared import Inches, Pt

from document_builder.helpers.docx_helper import add_paragraph_bottom_rule, run
from config.report_config import NAVY


def add_section_heading(doc: DocumentType) -> None:
    sp2 = doc.add_paragraph()
    sp2.paragraph_format.space_before = Pt(0)
    sp2.paragraph_format.space_after = Pt(10)

    sec_heading = doc.add_paragraph()
    sec_heading.paragraph_format.space_before = Pt(0)
    sec_heading.paragraph_format.space_after = Pt(2)
    add_paragraph_bottom_rule(sec_heading, color="#000F47", size=6)
    run(sec_heading, "Executive Narrative", bold=True, size_pt=13, color=NAVY)

    sp3 = doc.add_paragraph()
    sp3.paragraph_format.space_before = Pt(0)
    sp3.paragraph_format.space_after = Pt(6)
