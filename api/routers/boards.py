"""/api/boards CRUD."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.queries import board_posting_counts
from api.schemas import Board, BoardCreate, BoardListResponse, BoardUpdate, as_utc
from scraper.database import get_db
from scraper.models import StartUrl

router = APIRouter(prefix="/api/boards", tags=["boards"])

_DUPLICATE_DETAIL = "A board with that name or url already exists"


def _to_board(board: StartUrl, posting_count: int | None) -> Board:
    return Board(
        id=board.id,
        name=board.name,
        url=board.url,
        type=board.type,
        posting_count=posting_count,
        health=None,
        created_at=as_utc(board.created_at),
        updated_at=as_utc(board.updated_at),
    )


def _conflicting_board(
    db: Session, name: str, url: str, exclude_id: UUID | None
) -> StartUrl | None:
    query = db.query(StartUrl).filter(or_(StartUrl.name == name, StartUrl.url == url))
    if exclude_id is not None:
        query = query.filter(StartUrl.id != exclude_id)
    return query.first()


@router.get("", response_model=BoardListResponse)
def list_boards(
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI's own dependency-injection idiom
) -> BoardListResponse:
    boards = db.query(StartUrl).order_by(StartUrl.name).all()
    counts = board_posting_counts(db, [board.id for board in boards])
    return BoardListResponse(
        items=[_to_board(board, counts.get(board.id)) for board in boards]
    )


@router.post("", response_model=Board, status_code=201)
def create_board(
    payload: BoardCreate,
    db: Session = Depends(get_db),  # noqa: B008 - FastAPI's own dependency-injection idiom
) -> Board:
    if _conflicting_board(db, payload.name, payload.url, exclude_id=None):
        raise HTTPException(status_code=409, detail=_DUPLICATE_DETAIL)

    board = StartUrl(name=payload.name, url=payload.url, type=payload.type)
    db.add(board)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=_DUPLICATE_DETAIL) from exc
    db.refresh(board)
    return _to_board(board, None)


@router.put("/{board_id}", response_model=Board)
def update_board(
    board_id: UUID,
    payload: BoardUpdate,
    db: Session = Depends(get_db),  # noqa: B008
) -> Board:
    board = db.query(StartUrl).filter(StartUrl.id == board_id).one_or_none()
    if board is None:
        raise HTTPException(status_code=404, detail="No board with that id")
    if _conflicting_board(db, payload.name, payload.url, exclude_id=board_id):
        raise HTTPException(status_code=409, detail=_DUPLICATE_DETAIL)

    board.name = payload.name
    board.url = payload.url
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=_DUPLICATE_DETAIL) from exc
    db.refresh(board)
    counts = board_posting_counts(db, [board.id])
    return _to_board(board, counts.get(board.id))


@router.delete("/{board_id}", status_code=204)
def delete_board(
    board_id: UUID,
    db: Session = Depends(get_db),  # noqa: B008
) -> Response:
    board = db.query(StartUrl).filter(StartUrl.id == board_id).one_or_none()
    if board is None:
        raise HTTPException(status_code=404, detail="No board with that id")
    db.delete(board)
    db.commit()
    return Response(status_code=204)
