import contextlib

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, field_validator


class T(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TeamMember(T):
    name: str
    role: str = ""
    committee: str = "other"
    image_name: str = ""
    github: AnyHttpUrl | None = None
    linkedin: AnyHttpUrl | None = None
    website: AnyHttpUrl | None = None
    twitter: AnyHttpUrl | None = None
    bluesky: AnyHttpUrl | None = None
    mastodon: AnyHttpUrl | None = None
    image_url: AnyHttpUrl | None = None

    @field_validator("image_url", "github", "linkedin", "website", "twitter", "bluesky", "mastodon", mode="before")
    def validate_url(cls, value):
        if isinstance(value, AnyHttpUrl):
            return value
        if value and isinstance(value, str):
            with contextlib.suppress(Exception):
                value = AnyHttpUrl(value.strip())
                return value


class Committee(T):
    name: str
    comment: str = ""
    members: list[TeamMember]


class TeamDataBag(T):
    team_images: str
    default_image: str
    types: list[Committee]
