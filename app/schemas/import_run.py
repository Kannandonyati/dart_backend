"""Import Run / Imported Row response shapes. No request body schema for
`POST .../imports` — it's a multipart upload (`app_number` form field +
`file`), handled directly as FastAPI `Form`/`UploadFile` parameters in
the endpoint, not a JSON body."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.import_run import ImportStatus


class ImportRunRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    app_number: int
    file_name: str
    status: ImportStatus
    row_count: int | None
    error_message: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ImportedRowRead(BaseModel):
    id: uuid.UUID
    row_number: int
    data: dict[str, str]
    kickout: bool
