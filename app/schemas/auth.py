from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr | None = None
    password: str = Field(..., min_length=6)
    mobile: str | None = Field(None, description="E.164 like +989... or local")


class LoginRequest(BaseModel):
    # Deprecated: kept for compatibility (not used in OTP flow)
    username: str | None = None
    password: str | None = None


class TokenResponse(BaseModel):
    # Frontend contract:
    # export interface UserResponse {
    #   accessToken: string;
    #   sessionId: string;
    #   sessionExpiry: number;
    # }
    accessToken: str
    sessionId: str
    # Unix timestamp (seconds) when the session/access token expires
    sessionExpiry: int


class SendOtpRequest(BaseModel):
    mobile: str = Field(..., min_length=5, max_length=20)


class VerifyOtpRequest(BaseModel):
    mobile: str = Field(..., min_length=5, max_length=20)
    code: str = Field(..., min_length=5, max_length=5)


class UpdateProfileRequest(BaseModel):
    username: str | None = Field(None, min_length=3, max_length=50)
    email: EmailStr | None = None
