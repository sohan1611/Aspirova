import datetime as dt
import enum
from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import NoneType, UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from uuid import uuid4

import pytest
from pydantic import BaseModel

from api.schemas import OpportunityDetail, OpportunityListItem


def _default_value(name: str, annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Annotated:
        return _default_value(name, args[0])

    if origin in (Union, UnionType):
        non_none_args = [arg for arg in args if arg is not NoneType]
        if len(non_none_args) != len(args):
            return None
        if non_none_args:
            return _default_value(name, non_none_args[0])

    if origin is Literal:
        return args[0]

    if origin in (list, set, tuple, Sequence):
        return []

    if origin in (dict, Mapping):
        return {}

    lower_name = name.lower()
    if "url" in lower_name or "link" in lower_name:
        return "https://example.com"
    if "email" in lower_name:
        return "person@example.com"

    if annotation is Any or annotation is str:
        return "value"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return False
    if annotation is Decimal:
        return Decimal("1.0")
    if annotation is dt.datetime:
        return dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    if annotation is dt.date:
        return dt.date(2026, 1, 1)

    if isinstance(annotation, type):
        if issubclass(annotation, BaseModel):
            return _build_model(annotation)
        if issubclass(annotation, enum.Enum):
            return next(iter(annotation))
        if annotation.__name__.endswith("Url"):
            return "https://example.com"
        if annotation.__name__ == "EmailStr":
            return "person@example.com"
        if annotation.__name__ == "UUID":
            return uuid4()

    return "value"


def _build_model(model_cls: type[BaseModel], **overrides: Any) -> BaseModel:
    values: dict[str, Any] = {}
    for name, field in model_cls.model_fields.items():
        if name in overrides:
            value = overrides[name]
        elif field.is_required():
            value = _default_value(name, field.annotation)
        else:
            continue
        values[field.alias or name] = value
    return model_cls(**values)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Montego Bay, ", "Montego Bay"),
        ("Gurgaon, Gurgaon, Haryana, India", "Gurgaon, Haryana, India"),
        (", , ", None),
        ("", None),
        (None, None),
        ("Remote", "Remote"),
        ("  Bengaluru ,  Karnataka ", "Bengaluru, Karnataka"),
    ],
)
def test_opportunity_list_item_cleans_location(raw: str | None, expected: str | None) -> None:
    item = _build_model(OpportunityListItem, location=raw)

    assert item.location == expected


def test_opportunity_detail_inherits_location_cleaning() -> None:
    detail = _build_model(OpportunityDetail, location="Victoria, ")

    assert detail.location == "Victoria"
