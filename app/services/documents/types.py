from dataclasses import dataclass


@dataclass(slots=True)
class DocumentParagraph:
    paragraph_id: str
    page: int
    start_offset: int
    end_offset: int
    text: str


@dataclass(slots=True)
class DocumentParseResult:
    file_name: str
    file_type: str
    full_text: str
    paragraphs: list[DocumentParagraph]
