from enum import StrEnum


class ReviewStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class PromptType(StrEnum):
    CHARACTER = "character"
    SCENE = "scene"


class AliasType(StrEnum):
    NAME = "name"
    TITLE = "title"
    NICKNAME = "nickname"
    DISGUISE = "disguise"
    UNKNOWN = "unknown"


class EventType(StrEnum):
    APPEARANCE = "appearance"
    IDENTITY = "identity"
    RELATIONSHIP = "relationship"
    MOTIVATION = "motivation"
    OTHER = "other"
