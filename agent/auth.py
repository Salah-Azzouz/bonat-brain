import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from pydantic import BaseModel, validator

from agent.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, get_mongodb_collections, DEFAULT_MERCHANT, ALLOWED_MERCHANTS

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pydantic models
class UserRegistration(BaseModel):
    email: str
    password: str
    # Note: merchant_id is no longer stored per user - it's selected via UI at runtime

    @validator('email')
    def validate_email(cls, v):
        if not v.endswith('@bonat.io'):
            raise ValueError('Email must be a valid @bonat.io address')
        return v

class SwitchMerchantRequest(BaseModel):
    merchant_id: str

    @validator('merchant_id')
    def validate_merchant_id(cls, v):
        if v not in ALLOWED_MERCHANTS:
            raise ValueError(f'Invalid merchant ID. Allowed: {ALLOWED_MERCHANTS}')
        return v

class UserLogin(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    user_id: str
    email: str
    merchant_id: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class ChatRequest(BaseModel):
    user_query: str
    conversation_id: Optional[str] = None
    language: str = "ar"  # "ar" (default) or "en"

class ChatResponse(BaseModel):
    ai_response: str
    conversation_id: str
    message_id: str

class UserPreferencesUpdate(BaseModel):
    preferred_language: str = "ar"

class AuthService:
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    def register_user(self, user_data: UserRegistration) -> UserResponse:
        collections = get_mongodb_collections()
        if not collections:
            raise ValueError("Database connection failed")

        existing_user = collections["users"].find_one({"email": user_data.email})
        if existing_user:
            raise ValueError("Email already registered")

        user_id = str(uuid.uuid4())
        hashed_password = self.get_password_hash(user_data.password)

        # Note: merchant_id is no longer stored per user
        # All users get DEFAULT_MERCHANT on login, can switch via UI

        user_doc = {
            "user_id": user_id,
            "email": user_data.email,
            "hashed_password": hashed_password,
            "created_at": datetime.now(timezone.utc),
            # Proactive insights tracking fields
            "last_login": None,  # Will be set on first login
            "last_insight_date": None,  # Date insights were last shown (midnight UTC)
            "insight_shown_count": 0,  # Counter for insights shown
        }

        collections["users"].insert_one(user_doc)
        logging.info(f"New user registered: {user_data.email}")

        return UserResponse(
            user_id=user_id,
            email=user_data.email,
            merchant_id=DEFAULT_MERCHANT,  # Always return default on registration
        )

    def login_user(self, user_data: UserLogin) -> TokenResponse:
        collections = get_mongodb_collections()
        if not collections:
            raise ValueError("Database connection failed")

        user_doc = collections["users"].find_one({"email": user_data.email})
        if not user_doc or not self.verify_password(user_data.password, user_doc["hashed_password"]):
            raise ValueError("Invalid email or password")

        # Always use DEFAULT_MERCHANT on login (can be switched via UI)
        user = UserResponse(
            user_id=user_doc["user_id"],
            email=user_doc["email"],
            merchant_id=DEFAULT_MERCHANT,
        )

        access_token = self.create_access_token(
            data={"sub": user.email, "user_id": user.user_id, "merchant_id": user.merchant_id}
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=user
        )

    def switch_merchant(self, current_user: 'UserResponse', new_merchant_id: str) -> TokenResponse:
        """
        Create a new token with a different merchant_id.
        Used when user switches merchants via UI.
        """
        if new_merchant_id not in ALLOWED_MERCHANTS:
            raise ValueError(f"Invalid merchant ID. Allowed: {ALLOWED_MERCHANTS}")

        # Create new user response with updated merchant_id
        updated_user = UserResponse(
            user_id=current_user.user_id,
            email=current_user.email,
            merchant_id=new_merchant_id,
        )

        # Generate new token with new merchant_id
        access_token = self.create_access_token(
            data={"sub": updated_user.email, "user_id": updated_user.user_id, "merchant_id": updated_user.merchant_id}
        )

        logging.info(f"User {current_user.email} switched to merchant_id: {new_merchant_id}")

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=updated_user
        )

    def update_user_preferences(self, user_id: str, preferences: 'UserPreferencesUpdate') -> bool:
        """Update user preferences in MongoDB."""
        collections = get_mongodb_collections()
        if not collections:
            raise ValueError("Database connection failed")
        result = collections["users"].update_one(
            {"user_id": user_id},
            {"$set": {"preferred_language": preferences.preferred_language}}
        )
        return result.modified_count > 0

    def get_user_preferences(self, user_id: str) -> dict:
        """Read user preferences from MongoDB. Returns defaults if not set."""
        collections = get_mongodb_collections()
        if not collections:
            return {"preferred_language": "ar"}
        user_doc = collections["users"].find_one({"user_id": user_id})
        if not user_doc:
            return {"preferred_language": "ar"}
        return {"preferred_language": user_doc.get("preferred_language", "ar")}

    def get_current_user(self, token: str) -> Optional[UserResponse]:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: str = payload.get("sub")
            user_id: str = payload.get("user_id")
            # Always use hardcoded DEFAULT_MERCHANT, ignore token's merchant_id

            if email is None or user_id is None:
                return None

            return UserResponse(
                user_id=user_id,
                email=email,
                merchant_id=DEFAULT_MERCHANT,
            )
        except JWTError:
            return None

auth_service = AuthService()