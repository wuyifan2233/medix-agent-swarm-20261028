from fastapi import APIRouter, Depends, Request
from auth.dependencies import require_user
from auth.schemas import CurrentUser
from personalization.schemas import SaveProfile, ConfirmProfile, DeleteProfile, RestoreProfile
from personalization.store import ProfileStore

router = APIRouter(prefix="/api/profile", tags=["health-profile"])


def store(request: Request):
    return ProfileStore(request.app.state.auth_service.sessions)


@router.get("")
def read(user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return profiles.load(user.id)


@router.put("")
def save(command: SaveProfile, user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return profiles.save(user.id, command)


@router.post("/confirm")
def confirm(command: ConfirmProfile, user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return profiles.confirm(user.id, command.expected_revision)


@router.delete("")
def delete(command: DeleteProfile, user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return profiles.delete(user.id, command.expected_revision)


@router.get('/history')
def history(user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return {'items':profiles.history(user.id)}


@router.post('/restore')
def restore(command: RestoreProfile,user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return profiles.restore(user.id,command)


@router.get('/export')
def export(user: CurrentUser = Depends(require_user), profiles=Depends(store)):
    return {'schema_version':2,'profile':profiles.load(user.id)}
