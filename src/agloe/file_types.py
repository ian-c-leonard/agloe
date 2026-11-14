"""The shape of a FILE as Python types.

Generated from schema/file.schema.json by tools/generate_file_types.py. Do not edit.
"""

from typing import Literal, TypedDict

type Id = str


type Name = str


type Time = str


type Length = str


class Person(TypedDict):
    id: Id
    name: Name


class Place(TypedDict):
    id: Id
    name: Name


class OptionAtAPlace(TypedDict):
    id: Id
    name: Name
    place: Id


OptionBetweenPlaces = TypedDict(
    "OptionBetweenPlaces",
    {
        "id": Id,
        "name": Name,
        "from": Id,
        "to": Id,
    },
)


class FixedStart(TypedDict):
    id: Id
    option: Id
    starts_at: Time


class FreeStart(TypedDict):
    id: Id
    option: Id
    starts_any_time: Literal[True]


class ExactDuration(TypedDict):
    id: Id
    option: Id
    duration: Length


class Range(TypedDict):
    shortest: Length
    longest: Length


class ContingentDuration(TypedDict):
    id: Id
    option: Id
    contingent_duration: Range


class AccessCutoff(TypedDict):
    id: Id
    option: Id
    arrive_before_start: Length


class Span(TypedDict):
    earliest: Time
    latest: Time


Ways = TypedDict(
    "Ways",
    {
        "from": Id,
        "to": Id,
        "leaving": Span,
    },
)


class CompleteSet(TypedDict):
    id: Id
    complete: Ways


class Lock(TypedDict):
    id: Id
    lock: Id
    persons: list[Id]


class File(TypedDict):
    persons: list[Person]
    places: list[Place]
    options: list[OptionAtAPlace | OptionBetweenPlaces]
    facts: list[
        FixedStart | FreeStart | ExactDuration | ContingentDuration | AccessCutoff | CompleteSet
    ]
    decisions: list[Lock]
