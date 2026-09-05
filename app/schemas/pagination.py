"""Shared pagination envelope for list endpoints that need a real total.

Most list endpoints (recons, dimensions, etc.) return a bare array — fine
when the frontend paginates client-side over an already-small set. Manage
Users' three tables (`GET /users`, `GET /users/invited`, `GET
/audit-logs/mine`) render a "Page X of Y - N total" pager
(`SimplePagination`, `src/lib/api/pagination.ts`) that needs a real
`total_count` computed across the whole matching set — `len(current_page)`
alone can't produce that. This is that envelope, applied only where a
caller actually renders a total.
"""

from pydantic import BaseModel


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total_count: int
    has_more: bool


class PaginatedResponse[T](BaseModel):
    data: list[T]
    pagination: PaginationMeta


def build_pagination_meta(
    *, page: int, page_size: int, offset: int, total_count: int
) -> PaginationMeta:
    return PaginationMeta(
        page=page,
        page_size=page_size,
        total_count=total_count,
        has_more=offset + page_size < total_count,
    )
