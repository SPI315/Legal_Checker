from pydantic import BaseModel


class ParsedParagraph(BaseModel):
    paragraph_id: str
    page: int
    text: str


class ParseDocumentResponse(BaseModel):
    file_name: str
    file_type: str
    full_text: str
    paragraphs: list[ParsedParagraph]
