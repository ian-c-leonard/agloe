"""The shape of a FILE as Python types.

Generated from schema/file.schema.json by tools/generate_file_types.py. Do not edit.
"""

from typing import Literal, NotRequired, TypedDict

type Id = str


type Name = str


type Time = str


type Length = str


type Currency = str


type Amount = str


class Money(TypedDict):
    amount: Amount
    currency: Currency


class Payment(TypedDict):
    amount: Amount
    currency: Currency
    budget: NotRequired[Id]
    by: NotRequired[Id]


class Budget(TypedDict):
    id: Id
    name: Name
    persons: list[Id]
    objects: NotRequired[list[Id]]
    currencies: list[Currency]


class Person(TypedDict):
    id: Id
    name: Name


class Capability(TypedDict):
    id: Id
    name: Name


class Object(TypedDict):
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


class Ending(TypedDict):
    ends_at: Id


class Holder(TypedDict):
    person: Id
    degree: Literal[10, -10]


class Want(TypedDict):
    id: Id
    name: Name
    itinerary: NotRequired[Ending]
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


class NeedsRight(TypedDict):
    id: Id
    option: Id
    needs_right: bool


TermForCancelling = TypedDict(
    "TermForCancelling",
    {
        "from": NotRequired[Time],
        "costs": NotRequired[list[Money]],
    },
)


class Offer(TypedDict):
    option: Id
    places: int
    for_objects: NotRequired[list[Id]]
    prices: NotRequired[list[Money]]
    expires: NotRequired[Time]


class OfferFact(TypedDict):
    id: Id
    offer: Offer


class Rights(TypedDict):
    rights_to: Id
    offers: NotRequired[list[Id]]


class CompleteRights(TypedDict):
    id: Id
    complete: Rights


class StartsFrom(TypedDict):
    id: Id
    person: Id
    starts_from: Id


class HasCapability(TypedDict):
    id: Id
    person: Id
    capability: Id
    has: bool


class Requirement(TypedDict):
    capability: Id
    of: Literal["none", "one", "each"]


class RequiresCapability(TypedDict):
    id: Id
    option: Id
    requires: Requirement


class Requiring(TypedDict):
    requires: Id


class CompleteForACapability(TypedDict):
    id: Id
    complete: Requiring


class ObjectStartsWith(TypedDict):
    id: Id
    object: Id
    starts_with: Id


class ObjectStartsAt(TypedDict):
    id: Id
    object: Id
    starts_at: Id


class ObjectRequirement(TypedDict):
    object: Id
    needed: bool


class RequiresObject(TypedDict):
    id: Id
    option: Id
    requires: ObjectRequirement


class ObjectRefusal(TypedDict):
    object: Id
    refused: bool


class RefusesObject(TypedDict):
    id: Id
    option: Id
    refuses: ObjectRefusal


class ObjectRight(TypedDict):
    object: Id
    needed: bool


class NeedsRightForObject(TypedDict):
    id: Id
    option: Id
    needs_right_for: ObjectRight


class RightsForAnObject(TypedDict):
    rights_to: Id
    for_object: Id
    offers: NotRequired[list[Id]]


class CompleteRightsForAnObject(TypedDict):
    id: Id
    complete: RightsForAnObject


class TimeNow(TypedDict):
    id: Id
    now: Time


class NeedingARightForAnObject(TypedDict):
    needs_right_for: Id


class CompleteRightsNeededForAnObject(TypedDict):
    id: Id
    complete: NeedingARightForAnObject


class Action(TypedDict):
    object: Id
    does: Literal["hands_over", "keeps", "carries", "nothing"]


class WithObject(TypedDict):
    id: Id
    option: Id
    with_object: Action


class RequiringAnObject(TypedDict):
    requires_object: Id


class CompleteForAnObject(TypedDict):
    id: Id
    complete: RequiringAnObject


class Transferring(TypedDict):
    transfers: Id


class CompleteTransfers(TypedDict):
    id: Id
    complete: Transferring


class TripStart(TypedDict):
    id: Id
    trip_starts_at: Time


class TripEnd(TypedDict):
    id: Id
    trip_ends_at: Time


class Cap(TypedDict):
    id: Id
    budget: Id
    spend_at_most: Money


class Lock(TypedDict):
    id: Id
    lock: Id
    persons: list[Id]


class Booking(TypedDict):
    option: Id
    covers: list[Id]
    paid: NotRequired[Payment]
    cancelling: NotRequired[list[TermForCancelling]]


class BookingFact(TypedDict):
    id: Id
    booking: Booking


class File(TypedDict):
    persons: list[Person]
    places: list[Place]
    budgets: NotRequired[list[Budget]]
    capabilities: NotRequired[list[Capability]]
    objects: NotRequired[list[Object]]
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
        | StartsFrom
        | NeedsRight
        | BookingFact
        | OfferFact
        | CompleteRights
        | HasCapability
        | RequiresCapability
        | CompleteForACapability
        | ObjectStartsWith
        | ObjectStartsAt
        | RequiresObject
        | RefusesObject
        | WithObject
        | CompleteForAnObject
        | CompleteTransfers
        | NeedsRightForObject
        | CompleteRightsNeededForAnObject
        | CompleteRightsForAnObject
        | TimeNow
    ]
    decisions: list[Lock | TripStart | TripEnd | Cap]
