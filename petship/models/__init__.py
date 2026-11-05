"""SQLAlchemy models for PetShip.

Models are imported here so that Alembic's autogenerate (via Flask-Migrate)
sees every table on the shared ``db.metadata``. As new models are added in
later tasks, import them in this module.
"""
from __future__ import annotations

from .application import AdoptionAgreement, Application, ApplicationStage, ReturnStatus
from .appointment import Appointment, AppointmentKind, AppointmentStatus
from .chat import ChatMessage, Conversation
from .content import BlogPost, ContactMessage, FAQ, SuccessStory
from .favourite import Favourite
from .lifestyle import (
    EXPENSE_CATEGORIES,
    ExpenseFrequency,
    ExpenseItem,
    Place,
    PlaceCategory,
)
from .health import (
    HealthPlan,
    MedicalRecord,
    OwnedPet,
    RecordType,
    Vaccination,
    VaccineStatus,
    VetPatient,
)
from .community import POST_TOPICS, Comment, Follow, Post, PostLike
from .learning import LearningPath, Lesson, LessonProgress
from .lostfound import FoundPetTip, LostFoundReport, ReportKind, ReportStatus
from .message import Message, Thread
from .report import AbuseReport, AbuseStatus, ReportTargetType
from .reminder import Notification, Recurrence, Reminder
from .review import FollowUp, FollowUpStatus, Review, ReviewTarget
from .vet import VetProfile
from .pet import (
    AgeGroup,
    Pet,
    PetStatus,
    Sex,
    Size,
    Species,
)
from .platform import PlatformFeedback, PlatformMetricEvent
from .shelter import Shelter
from .user import User

__all__ = [
    "User",
    "Shelter",
    "Pet",
    "Species",
    "AgeGroup",
    "Size",
    "Sex",
    "PetStatus",
    "BlogPost",
    "SuccessStory",
    "FAQ",
    "ContactMessage",
    "Favourite",
    "Application",
    "AdoptionAgreement",
    "ApplicationStage",
    "ReturnStatus",
    "Appointment",
    "AppointmentKind",
    "AppointmentStatus",
    "Review",
    "ReviewTarget",
    "FollowUp",
    "FollowUpStatus",
    "VetProfile",
    "OwnedPet",
    "VetPatient",
    "HealthPlan",
    "MedicalRecord",
    "RecordType",
    "Vaccination",
    "VaccineStatus",
    "ExpenseItem",
    "ExpenseFrequency",
    "Place",
    "PlaceCategory",
    "Reminder",
    "Recurrence",
    "Notification",
    "LearningPath",
    "Lesson",
    "LessonProgress",
    "Conversation",
    "ChatMessage",
    "LostFoundReport",
    "FoundPetTip",
    "ReportKind",
    "ReportStatus",
    "Post",
    "Comment",
    "PostLike",
    "Follow",
    "POST_TOPICS",
    "AbuseReport",
    "ReportTargetType",
    "AbuseStatus",
    "Thread",
    "Message",
    "PlatformFeedback",
    "PlatformMetricEvent",
]
