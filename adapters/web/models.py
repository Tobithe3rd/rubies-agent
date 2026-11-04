"""Pydantic request/response models for the web adapter."""
from pydantic import BaseModel


class MessageBody(BaseModel):
    message: str


class ChatResponse(BaseModel):
    chat_id: str


class MessageResponse(BaseModel):
    reply: str
    error: bool = False


class OtpResponse(BaseModel):
    otp_line: str
