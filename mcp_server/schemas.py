from pydantic import BaseModel, Field


class PaginationInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=100000)


class ClipSearchInput(PaginationInput):
    query: str = ""
    visibility: str = Field(default="all", pattern="^(all|public|private|mine)$")


class ClipIdInput(BaseModel):
    clip_id: int = Field(ge=1)


class RecentStudyInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=100)


class VideoSearchInput(PaginationInput):
    query: str = ""
    mine_only: bool = True


class VideoIdInput(BaseModel):
    master_video_id: int = Field(ge=1)


class BatchIdInput(BaseModel):
    batch_id: int = Field(ge=1)
