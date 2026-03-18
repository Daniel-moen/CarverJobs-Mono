from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, flags, metrics, schemas
from app.database import get_db
from app.logger import get_logger
from app.security import require_admin_session

log = get_logger("carver.users")
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin_session)])


@router.get("", response_model=list[schemas.UserRead])
def list_users(db: Session = Depends(get_db)):
    users = crud.list_users(db)
    log.info("Users listed | count=%d", len(users))
    return users


@router.post("", response_model=schemas.UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if not flags.is_enabled("user_registration"):
        metrics.increment("feature_blocked")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="User registration is temporarily disabled.")
    existing = crud.get_user_by_email(db, payload.email.lower().strip())
    if existing:
        log.warning("User creation failed: email exists | email=%s", payload.email)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    user = crud.create_user(db, payload)
    log.info("User created | id=%d | email=%s", user.id, user.email)
    return user


@router.get("/{user_id}", response_model=schemas.UserRead)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        log.warning("User not found | id=%d", user_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=schemas.UserRead)
def update_user(user_id: int, payload: schemas.UserUpdate, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        log.warning("User update failed: not found | id=%d", user_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated = crud.update_user(db, user, payload)
    log.info("User updated | id=%d", user_id)
    return updated


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(user_id: int, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        log.warning("User delete failed: not found | id=%d", user_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    crud.delete_user(db, user)
    log.info("User deleted | id=%d", user_id)
    return None
