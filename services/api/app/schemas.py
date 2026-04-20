from pydantic import BaseModel


class TerraformCommand(BaseModel):
    args: list[str] = []
    var_file: str | None = None


class FileContent(BaseModel):
    content: str


class ChatMessage(BaseModel):
    message: str
    context: str | None = None


class ChatSessionMessage(BaseModel):
    role: str
    content: str


class ChatSessionRequest(BaseModel):
    messages: list[ChatSessionMessage]


class DiagnoseRequest(BaseModel):
    command: str
    output: str


class SummarizeRequest(BaseModel):
    resources: list[dict]
