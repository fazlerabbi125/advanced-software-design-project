from datetime import datetime

from pydantic import BaseModel


class BiometricImageResponse(BaseModel):
    image_key: str
    content_type: str
    uploaded_at: datetime
