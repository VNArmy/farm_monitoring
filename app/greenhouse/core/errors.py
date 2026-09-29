"""Lỗi có mã và trường, web trả về dạng {"error": {"code", "message", "field"}} (spec mục 9)."""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field

    def to_dict(self) -> dict[str, dict[str, str | None]]:
        return {"error": {"code": self.code, "message": self.message, "field": self.field}}


def invalid(message: str, field: str | None = None, code: str = "invalid") -> ApiError:
    return ApiError(400, code, message, field)


def conflict(message: str, code: str, field: str | None = None) -> ApiError:
    return ApiError(409, code, message, field)


def not_found(message: str = "Không tìm thấy") -> ApiError:
    return ApiError(404, "not_found", message)
