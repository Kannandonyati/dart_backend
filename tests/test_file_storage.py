import pytest

from app.services.file_storage import (
    delete_upload_async,
    read_upload_async,
    save_upload_async,
)


@pytest.mark.asyncio
async def test_async_upload_round_trip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path))
    from app.core.config import settings

    monkeypatch.setattr(settings, "upload_storage_dir", str(tmp_path))
    path = await save_upload_async(b"year,amount\n2024,1")
    assert (await read_upload_async(path)) == b"year,amount\n2024,1"
    await delete_upload_async(path)
    with pytest.raises(FileNotFoundError):
        await read_upload_async(path)
