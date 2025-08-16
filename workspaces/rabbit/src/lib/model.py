from pydantic import BaseModel


class Pose(BaseModel):
    translation: list[float]
    orientation: list[float]
    frame_number: int
    timestamp: int


class CameraIntrinsics(BaseModel):
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int
