"""The shape of a FILE as Python types.

Generated from schema/file.schema.json by tools/generate_file_types.py. Do not edit.
"""

from typing import Literal, NotRequired, TypedDict

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


WayOneWay = TypedDict(
    "WayOneWay",
    {
        "id": Id,
        "name": Name,
        "from": Id,
        "to": Id,
    },
)


class WayBothWays(TypedDict):
    id: Id
    name: Name
    between: list[Id]


class Holder(TypedDict):
    person: Id
    degree: Literal[10, -10]


class Want(TypedDict):
    id: Id
    name: Name
    holders: list[Holder]


class Range(TypedDict):
    shortest: Length
    longest: Length


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


class ContingentDuration(TypedDict):
    id: Id
    option: Id
    contingent_duration: Range


class WayDuration(TypedDict):
    id: Id
    way: Id
    duration: Length


class WayContingentDuration(TypedDict):
    id: Id
    way: Id
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
        "from": NotRequired[Id],
        "to": NotRequired[Id],
        "leaving": Span,
    },
)


class CompleteSet(TypedDict):
    id: Id
    complete: Ways


class Satisfaction(TypedDict):
    want: Id
    degree: int


class Satisfies(TypedDict):
    id: Id
    option: Id
    satisfies: Satisfaction


class Satisfying(TypedDict):
    satisfies: Id


class CompleteForAWant(TypedDict):
    id: Id
    complete: Satisfying


class Lock(TypedDict):
    id: Id
    lock: Id
    persons: list[Id]


class File(TypedDict):
    persons: list[Person]
    places: list[Place]
    options: list[OptionAtAPlace | OptionBetweenPlaces]
    ways: list[WayOneWay | WayBothWays]
    wants: list[Want]
    facts: list[
        FixedStart
        | FreeStart
        | ExactDuration
        | ContingentDuration
        | AccessCutoff
        | WayDuration
        | WayContingentDuration
        | CompleteSet
        | Satisfies
        | CompleteForAWant
    ]
    decisions: list[Lock]
