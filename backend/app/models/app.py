from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, model_validator


class AppBase(BaseModel):
    app_id: str
    name: str
    description: str = ""
    category: str = ""
    icon: str = ""
    enabled: bool = True


class AppCreate(AppBase):
    pass


class AppUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    enabled: Optional[bool] = None


class AppResponse(AppBase):
    connected: bool = False
    capabilities: List[str] = []
    id: str = ""

    @model_validator(mode="after")
    def set_id(self):
        if not self.id:
            self.id = self.app_id
        return self