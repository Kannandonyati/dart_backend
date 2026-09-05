from pydantic import BaseModel, Field


class GlobalVariableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GlobalVariableRead(BaseModel):
    name: str
