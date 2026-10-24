from app.schemas.user import Name, Password, StrictRequest, Username, UserResponse


class LoginRequest(StrictRequest):
    username: Username
    password: Password


class LoginResponse(StrictRequest):
    token: str
    user: UserResponse


class RegisterRequest(StrictRequest):
    username: Username
    password: Password
    name: Name | None = None
