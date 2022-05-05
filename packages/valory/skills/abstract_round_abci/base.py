# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2022 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This module contains the base classes for the models classes of the skill."""
import datetime
import heapq
import itertools
import logging
import textwrap
import uuid
from abc import ABC, ABCMeta, abstractmethod
from collections import Counter
from copy import copy, deepcopy
from dataclasses import dataclass, field
from enum import Enum
from math import ceil
from typing import (
    Any,
    Dict,
    FrozenSet,
    Generic,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    cast,
)

from aea.crypto.ledger_apis import LedgerApis
from aea.exceptions import enforce

from packages.valory.connections.ledger.base import (
    CONNECTION_ID as LEDGER_CONNECTION_PUBLIC_ID,
)
from packages.valory.protocols.abci.custom_types import Header
from packages.valory.skills.abstract_round_abci import serializer


_logger = logging.getLogger("aea.packages.valory.skills.abstract_round_abci.base")

OK_CODE = 0
ERROR_CODE = 1
LEDGER_API_ADDRESS = str(LEDGER_CONNECTION_PUBLIC_ID)
ROUND_COUNT_DEFAULT = -1
MIN_HISTORY_DEPTH = 1
ADDRESS_LENGTH = 42
MAX_INT_256 = 2 ** 256 - 1

EventType = TypeVar("EventType")
TransactionType = TypeVar("TransactionType")


def consensus_threshold(n: int) -> int:  # pylint: disable=invalid-name
    """
    Get consensus threshold.

    :param n: the number of participants
    :return: the consensus threshold
    """
    return ceil((2 * n + 1) / 3)


class ABCIAppException(Exception):
    """A parent class for all exceptions related to the ABCIApp."""


class SignatureNotValidError(ABCIAppException):
    """Error raised when a signature is invalid."""


class AddBlockError(ABCIAppException):
    """Exception raised when a block addition is not valid."""


class ABCIAppInternalError(ABCIAppException):
    """Internal error due to a bad implementation of the ABCIApp."""

    def __init__(self, message: str, *args: Any) -> None:
        """Initialize the error object."""
        super().__init__("internal error: " + message, *args)


class TransactionTypeNotRecognizedError(ABCIAppException):
    """Error raised when a transaction type is not recognized."""


class TransactionNotValidError(ABCIAppException):
    """Error raised when a transaction is not valid."""


class LateArrivingTransaction(ABCIAppException):
    """Error raised when the transaction belongs to previous round."""


class _MetaPayload(ABCMeta):
    """
    Payload metaclass.

    The purpose of this metaclass is to remember the association
    between the type of payload and the payload class to build it.
    This is necessary to recover the right payload class to instantiate
    at decoding time.

    Each class that has this class as metaclass must have a class
    attribute 'transaction_type', which for simplicity is required
    to be convertible to string, for serialization purposes.
    """

    transaction_type_to_payload_cls: Dict[str, Type["BaseTxPayload"]] = {}

    def __new__(mcs, name: str, bases: Tuple, namespace: Dict, **kwargs: Any) -> Type:  # type: ignore
        """Create a new class object."""
        new_cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        if ABC in bases:
            # abstract class, return
            return new_cls
        if not issubclass(new_cls, BaseTxPayload):
            raise ValueError(  # pragma: no cover
                f"class {name} must inherit from {BaseTxPayload.__name__}"
            )
        new_cls = cast(Type[BaseTxPayload], new_cls)

        transaction_type = str(mcs._get_field(new_cls, "transaction_type"))
        mcs._validate_transaction_type(transaction_type, new_cls)
        # remember association from transaction type to payload class
        mcs.transaction_type_to_payload_cls[transaction_type] = new_cls

        return new_cls

    @classmethod
    def _validate_transaction_type(
        mcs, transaction_type: str, new_payload_cls: Type["BaseTxPayload"]
    ) -> None:
        """Check that a transaction type is not already associated to a concrete payload class."""
        if transaction_type in mcs.transaction_type_to_payload_cls:
            previous_payload_cls = mcs.transaction_type_to_payload_cls[transaction_type]
            if new_payload_cls.__name__ != previous_payload_cls.__name__:
                raise ValueError(
                    f"transaction type with name {transaction_type} already "
                    f"used by class {previous_payload_cls}, and cannot be "
                    f"used by class {new_payload_cls} "
                )

    @classmethod
    def _get_field(mcs, cls: Type, field_name: str) -> Any:
        """Get a field from a class if present, otherwise raise error."""
        if not hasattr(cls, field_name) or getattr(cls, field_name) is None:
            raise ValueError(f"class {cls} must set '{field_name}' class field")
        return getattr(cls, field_name)


class BaseTxPayload(ABC, metaclass=_MetaPayload):
    """This class represents a base class for transaction payload classes."""

    transaction_type: Any

    def __init__(
        self,
        sender: str,
        id_: Optional[str] = None,
        round_count: int = ROUND_COUNT_DEFAULT,
    ) -> None:
        """
        Initialize a transaction payload.

        :param sender: the sender (Ethereum) address
        :param id_: the id of the transaction
        :param round_count: the count of the round in which the payload was sent
        """
        self.id_ = uuid.uuid4().hex if id_ is None else id_
        self._round_count = round_count
        self.sender = sender

    @property
    def round_count(self) -> int:
        """Get the round count."""
        return self._round_count

    @round_count.setter
    def round_count(self, round_count: int) -> None:
        """Set the round count."""
        self._round_count = round_count

    def encode(self) -> bytes:
        """Encode the payload."""
        return serializer.to_bytes(self.json)

    @classmethod
    def decode(cls, obj: bytes) -> "BaseTxPayload":
        """Decode the payload."""
        return cls.from_json(serializer.from_bytes(obj))

    @classmethod
    def from_json(cls, obj: Dict) -> "BaseTxPayload":
        """Decode the payload."""
        data = copy(obj)
        transaction_type = str(data.pop("transaction_type"))
        payload_cls = _MetaPayload.transaction_type_to_payload_cls[transaction_type]
        return payload_cls(**data)

    @property
    def json(self) -> Dict:
        """Get the JSON representation of the payload."""
        return dict(
            transaction_type=str(self.transaction_type),
            id_=self.id_,
            sender=self.sender,
            round_count=self.round_count,
            **self.data,
        )

    @property
    def data(self) -> Dict:
        """
        Get the dictionary data.

        The returned dictionary is required to be used
        as keyword constructor initializer, i.e. these two
        should have the same effect:

            sender = "..."
            some_kwargs = {...}
            p1 = SomePayloadClass(sender, **some_kwargs)
            p2 = SomePayloadClass(sender, **p1.data)

        :return: a dictionary which contains the payload data
        """
        return {}

    def with_new_id(self) -> "BaseTxPayload":
        """Create a new payload with the same content but new id."""
        return type(self)(self.sender, id_=uuid.uuid4().hex, round_count=self.round_count, **self.data)  # type: ignore

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        if not isinstance(other, BaseTxPayload):
            return NotImplemented
        return (
            self.id_ == other.id_
            and self.round_count == other.round_count
            and self.sender == other.sender
            and self.data == other.data
        )

    def __hash__(self) -> int:
        """Hash the payload."""
        return hash(tuple(sorted(self.data.items())))


class Transaction(ABC):
    """Class to represent a transaction for the ephemeral chain of a period."""

    def __init__(self, payload: BaseTxPayload, signature: str) -> None:
        """Initialize a transaction object."""
        self.payload = payload
        self.signature = signature

    def encode(self) -> bytes:
        """Encode the transaction."""
        data = dict(payload=self.payload.json, signature=self.signature)
        return serializer.to_bytes(data)

    @classmethod
    def decode(cls, obj: bytes) -> "Transaction":
        """Decode the transaction."""
        data = serializer.from_bytes(obj)
        signature = data["signature"]
        payload_dict = data["payload"]
        payload = BaseTxPayload.from_json(payload_dict)
        return Transaction(payload, signature)

    def verify(self, ledger_id: str) -> None:
        """
        Verify the signature is correct.

        :param ledger_id: the ledger id of the address
        :raises: SignatureNotValidError: if the signature is not valid.
        """
        payload_bytes = serializer.to_bytes(self.payload.json)
        addresses = LedgerApis.recover_message(
            identifier=ledger_id, message=payload_bytes, signature=self.signature
        )
        if self.payload.sender not in addresses:
            raise SignatureNotValidError("signature not valid.")

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        if not isinstance(other, Transaction):
            return NotImplemented
        return self.payload == other.payload and self.signature == other.signature


class Block:  # pylint: disable=too-few-public-methods
    """Class to represent (a subset of) data of a Tendermint block."""

    def __init__(
        self,
        header: Header,
        transactions: Sequence[Transaction],
    ) -> None:
        """Initialize the block."""
        self.header = header
        self._transactions: Tuple[Transaction, ...] = tuple(transactions)

    @property
    def transactions(self) -> Tuple[Transaction, ...]:
        """Get the transactions."""
        return self._transactions

    @property
    def timestamp(self) -> datetime.datetime:
        """Get the block timestamp."""
        return self.header.timestamp


class Blockchain:
    """
    Class to represent a (naive) Tendermint blockchain.

    The consistency of the data in the blocks is guaranteed by Tendermint.
    """

    def __init__(self) -> None:
        """Initialize the blockchain."""
        self._blocks: List[Block] = []

    def add_block(self, block: Block) -> None:
        """Add a block to the list."""
        expected_height = self.height + 1
        actual_height = block.header.height
        if expected_height != actual_height:
            raise AddBlockError(
                f"expected height {expected_height}, got {actual_height}"
            )
        self._blocks.append(block)

    @property
    def height(self) -> int:
        """
        Get the height.

        Tendermint's height starts from 1. A return value
            equal to 0 means empty blockchain.

        :return: the height.
        """
        return self.length

    @property
    def length(self) -> int:
        """Get the blockchain length."""
        return len(self._blocks)

    @property
    def blocks(self) -> Tuple[Block, ...]:
        """Get the blocks."""
        return tuple(self._blocks)


class BlockBuilder:
    """Helper class to build a block."""

    _current_header: Optional[Header] = None
    _current_transactions: List[Transaction] = []

    def __init__(self) -> None:
        """Initialize the block builder."""
        self.reset()

    def reset(self) -> None:
        """Reset the temporary data structures."""
        self._current_header = None
        self._current_transactions = []

    @property
    def header(self) -> Header:
        """
        Get the block header.

        :return: the block header
        """
        if self._current_header is None:
            raise ValueError("header not set")
        return self._current_header

    @header.setter
    def header(self, header: Header) -> None:
        """Set the header."""
        if self._current_header is not None:
            raise ValueError("header already set")
        self._current_header = header

    @property
    def transactions(self) -> Tuple[Transaction, ...]:
        """Get the sequence of transactions."""
        return tuple(self._current_transactions)

    def add_transaction(self, transaction: Transaction) -> None:
        """Add a transaction."""
        self._current_transactions.append(transaction)

    def get_block(self) -> Block:
        """Get the block."""
        return Block(
            self.header,
            self._current_transactions,
        )


class ConsensusParams:
    """Represent the consensus parameters."""

    def __init__(self, max_participants: int):
        """Initialize the consensus parameters."""
        self._max_participants = max_participants

    @property
    def max_participants(self) -> int:
        """Get the maximum number of participants."""
        return self._max_participants

    @property
    def consensus_threshold(self) -> int:
        """Get the consensus threshold."""
        return consensus_threshold(self.max_participants)

    @classmethod
    def from_json(cls, obj: Dict) -> "ConsensusParams":
        """Get from JSON."""
        max_participants = obj["max_participants"]
        enforce(
            isinstance(max_participants, int) and max_participants >= 0,
            "max_participants must be an integer greater than 0.",
        )
        return cls(max_participants)

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        if not isinstance(other, ConsensusParams):
            return NotImplemented
        return self.max_participants == other.max_participants


class StateDB:
    """Class to represent all state replicated across periods."""

    def __init__(
        self,
        initial_period: int,
        initial_data: Dict[str, Any],
        cross_period_persisted_keys: Optional[List[str]] = None,
    ) -> None:
        """Initialize a period state."""
        self._current_period_count = initial_period
        self._initial_data = initial_data
        self._cross_period_persisted_keys = (
            [] if cross_period_persisted_keys is None else cross_period_persisted_keys
        )
        self._data: Dict[int, Dict[str, Any]] = {
            self._current_period_count: deepcopy(self._initial_data)
        }
        self._round_count = ROUND_COUNT_DEFAULT  # ensures first round is indexed at 0!

    @property
    def initial_data(self) -> Dict[str, Any]:
        """
        Get the initial_data.

        :return: the initial_data
        """
        return self._initial_data

    @property
    def current_period_count(self) -> int:
        """Get the current period count."""
        return self._current_period_count

    @property
    def round_count(self) -> int:
        """Get the round count."""
        return self._round_count

    @property
    def cross_period_persisted_keys(self) -> List[str]:
        """Keys in the period state which are persistet across periods."""
        return self._cross_period_persisted_keys

    def get(self, key: str, default: Any = "NOT_PROVIDED") -> Optional[Any]:
        """Get a value from the data dictionary."""
        if default != "NOT_PROVIDED":
            return self._data.get(self._current_period_count, {}).get(key, default)
        try:
            return self._data.get(self._current_period_count, {}).get(key)
        except KeyError as exception:  # pragma: no cover
            raise ValueError(
                f"'{key}' field is not set for period state."
            ) from exception

    def get_strict(self, key: str) -> Any:
        """Get a value from the data dictionary and raise if it is None."""
        value = self.get(key)
        if value is None:
            raise ValueError(
                f"Value of key={key} is None for "
                f"current_period_count={self.current_period_count} "
            )
        return value

    def update_current_period(self, **kwargs: Any) -> None:
        """Update the current period's state."""
        self._data[self._current_period_count].update(kwargs)

    def add_new_period(self, new_period: int, **kwargs: Any) -> None:
        """Update the current period's state."""
        # if new_period in self._data:
        #     raise ValueError(
        #         "Incorrect period count incrementation, period already exists"
        #     )  # pragma: no cover
        self._current_period_count = new_period
        self._data[self._current_period_count] = kwargs

    def get_all(self) -> Dict[str, Any]:
        """Get all key-value pairs from the data dictionary for the current period."""
        return self._data[self._current_period_count]

    def increment_round_count(self) -> None:
        """Increment the round count."""
        self._round_count += 1

    def __repr__(self) -> str:
        """Return a string representation of the state."""
        return f"StateDB({self._data})"

    def cleanup(self, cleanup_history_depth: int) -> None:
        """Reset the db."""
        cleanup_history_depth = max(cleanup_history_depth, MIN_HISTORY_DEPTH)
        self._data = {
            key: self._data[key]
            for key in sorted(self._data.keys())[-cleanup_history_depth:]
        }


class BasePeriodState:
    """
    Class to represent a period state.

    This is the relevant state constructed and replicated by the agents in a period.
    """

    def __init__(
        self,
        db: StateDB,
    ) -> None:
        """Initialize a period state."""
        self._db = db

    @property
    def db(self) -> StateDB:
        """Get DB."""
        return self._db

    @property
    def round_count(self) -> int:
        """Get the round count."""
        return self.db.round_count

    @property
    def period_count(self) -> int:
        """Get the period count."""
        return self.db.current_period_count

    @property
    def participants(self) -> FrozenSet[str]:
        """Get the participants."""
        participants = self.db.get_strict("participants")
        if len(participants) == 0:
            raise ValueError("List participants cannot be empty.")
        return cast(FrozenSet[str], participants)

    @property
    def all_participants(self) -> FrozenSet[str]:
        """Get all the participants."""
        all_participants = self.db.get_strict("all_participants")
        if len(all_participants) == 0:
            raise ValueError("List participants cannot be empty.")
        return cast(FrozenSet[str], all_participants)

    @property
    def sorted_participants(self) -> Sequence[str]:
        """
        Get the sorted participants' addresses.

        The addresses are sorted according to their hexadecimal value;
        this is the reason we use key=str.lower as comparator.

        This property is useful when interacting with the Safe contract.

        :return: the sorted participants' addresses
        """
        return sorted(self.participants, key=str.lower)

    @property
    def nb_participants(self) -> int:
        """Get the number of participants."""
        return len(self.participants)

    def update(
        self,
        period_state_class: Optional[Type] = None,
        period_count: Optional[int] = None,
        **kwargs: Any,
    ) -> "BasePeriodState":
        """Copy and update the state."""
        if period_count is None:
            self.db.update_current_period(**kwargs)
        else:
            self.db.add_new_period(new_period=period_count, **kwargs)
        class_ = type(self) if period_state_class is None else period_state_class
        return class_(db=self.db)

    def __repr__(self) -> str:
        """Return a string representation of the state."""
        return f"{self.__class__.__name__}(db={self._db})"

    @property
    def keeper_randomness(self) -> float:
        """Get the keeper's random number [0-1]."""
        return (
            int(self.most_voted_randomness, base=16) / MAX_INT_256
        )  # DRAND uses sha256 values

    @property
    def most_voted_randomness(self) -> str:
        """Get the most_voted_randomness."""
        return cast(str, self.db.get_strict("most_voted_randomness"))

    @property
    def most_voted_keeper_address(self) -> str:
        """Get the most_voted_keeper_address."""
        return cast(str, self.db.get_strict("most_voted_keeper_address"))

    @property
    def is_keeper_set(self) -> bool:
        """Check whether keeper is set."""
        return self.db.get("most_voted_keeper_address", None) is not None

    @property
    def blacklisted_keepers(self) -> Set[str]:
        """Get the current cycle's blacklisted keepers who cannot submit a transaction."""
        raw = cast(str, self.db.get("blacklisted_keepers", ""))
        return set(textwrap.wrap(raw, ADDRESS_LENGTH))

    @property
    def participant_to_selection(self) -> Mapping:
        """Check whether keeper is set."""
        return cast(Dict, self.db.get_strict("participant_to_selection"))

    @property
    def participant_to_randomness(self) -> Mapping:
        """Check whether keeper is set."""
        return cast(Dict, self.db.get_strict("participant_to_randomness"))

    @property
    def participant_to_votes(self) -> Mapping:
        """Check whether keeper is set."""
        return cast(Dict, self.db.get_strict("participant_to_votes"))


class AbstractRound(Generic[EventType, TransactionType], ABC):
    """
    This class represents an abstract round.

    A round is a state of a period. It usually involves
    interactions between participants in the period,
    although this is not enforced at this level of abstraction.

    Concrete classes must set:
    - round_id: the identifier for the concrete round class;
    - allowed_tx_type: the transaction type that is allowed for this round.
    """

    round_id: str
    allowed_tx_type: Optional[TransactionType]
    payload_attribute: str

    _previous_round_tx_type: Optional[TransactionType]

    def __init__(
        self,
        state: BasePeriodState,
        consensus_params: ConsensusParams,
        previous_round_tx_type: Optional[TransactionType] = None,
    ) -> None:
        """Initialize the round."""
        self._consensus_params = consensus_params
        self._state = state
        self.block_confirmations = 0
        self._previous_round_tx_type = previous_round_tx_type

        self._check_class_attributes()

    def _check_class_attributes(self) -> None:
        """Check that required class attributes are set."""
        try:
            self.round_id
        except AttributeError as exc:
            raise ABCIAppInternalError("'round_id' field not set") from exc
        try:
            self.allowed_tx_type
        except AttributeError as exc:
            raise ABCIAppInternalError("'allowed_tx_type' field not set") from exc

    @property
    def period_state(self) -> BasePeriodState:
        """Get the period state."""
        return self._state

    def check_transaction(self, transaction: Transaction) -> None:
        """
        Check transaction against the current state.

        :param transaction: the transaction
        """
        self.check_allowed_tx_type(transaction)
        self.check_payload(transaction.payload)

    def process_transaction(self, transaction: Transaction) -> None:
        """
        Process a transaction.

        By convention, the payload handler should be a method
        of the class that is named '{payload_name}'.

        :param transaction: the transaction.
        """
        self.check_allowed_tx_type(transaction)
        self.process_payload(transaction.payload)

    @abstractmethod
    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """
        Process the end of the block.

        The role of this method is check whether the round
        is considered ended.

        If the round is ended, the return value is
         - the final result of the round.
         - the event that triggers a transition. If None, the period
            in which the round was executed is considered ended.

        This is done after each block because we consider the consensus engine's
        block, and not the transaction, as the smallest unit
        on which the consensus is reached; in other words,
        each read operation on the state should be done
        only after each block, and not after each transaction.
        """

    def check_allowed_tx_type(self, transaction: Transaction) -> None:
        """
        Check the transaction is of the allowed transaction type.

        :param transaction: the transaction
        :raises: TransactionTypeNotRecognizedError if the transaction can be
                 applied to the current state.
        """
        if self.allowed_tx_type is None:
            raise TransactionTypeNotRecognizedError(
                "current round does not allow transactions"
            )
        tx_type = transaction.payload.transaction_type

        if self._previous_round_tx_type is not None and str(tx_type) == str(
            self._previous_round_tx_type
        ):
            raise LateArrivingTransaction(
                f"request '{tx_type}' is from previous round; skipping"
            )

        if str(tx_type) != str(self.allowed_tx_type):
            raise TransactionTypeNotRecognizedError(
                f"request '{tx_type}' not recognized; only {self.allowed_tx_type} is supported"
            )

    @classmethod
    def check_majority_possible_with_new_voter(
        cls,
        votes_by_participant: Dict[Any, Any],
        new_voter: Any,
        new_vote: Any,
        nb_participants: int,
        exception_cls: Type[ABCIAppException] = ABCIAppException,
    ) -> None:
        """
        Check that a Byzantine majority is achievable, once a new vote is added.

         :param votes_by_participant: a mapping from a participant to its vote,
                before the new vote is added
         :param new_voter: the new voter
         :param new_vote: the new vote
         :param nb_participants: the total number of participants
         :param exception_cls: the class of the exception to raise in case the
                               check fails.
         :raises: exception_cls: in case the check does not pass.
        """
        # check preconditions
        enforce(
            new_voter not in votes_by_participant,
            "voter has already voted",
            ABCIAppInternalError,
        )
        enforce(
            len(votes_by_participant) <= nb_participants - 1,
            "nb_participants not consistent with votes_by_participants",
            ABCIAppInternalError,
        )

        # copy the input dictionary to avoid side effects
        votes_by_participant = copy(votes_by_participant)

        # add the new vote
        votes_by_participant[new_voter] = new_vote

        cls.check_majority_possible(
            votes_by_participant, nb_participants, exception_cls=exception_cls
        )

    @classmethod
    def check_majority_possible(
        cls,
        votes_by_participant: Dict[Any, Any],
        nb_participants: int,
        exception_cls: Type[ABCIAppException] = ABCIAppException,
    ) -> None:
        """
        Check that a Byzantine majority is still achievable.

        The idea is that, even if all the votes have not been delivered yet,
        it can be deduced whether a quorum cannot be reached due to
        divergent preferences among the voters and due to a too small
        number of other participants whose vote has not been delivered yet.

        The check fails iff:

            nb_remaining_votes + largest_nb_votes < quorum

        That is, if the number of remaining votes is not enough to make
        the most voted item so far to exceed the quorum.

        Preconditions on the input:
        - the size of votes_by_participant should not be greater than
          "nb_participants - 1" voters
        - new voter must not be in the current votes_by_participant

        :param votes_by_participant: a mapping from a participant to its vote
        :param nb_participants: the total number of participants
        :param exception_cls: the class of the exception to raise in case the
                              check fails.
        :raises exception_cls: in case the check does not pass.
        """
        enforce(
            nb_participants > 0 and len(votes_by_participant) <= nb_participants,
            "nb_participants not consistent with votes_by_participants",
            ABCIAppInternalError,
        )
        if len(votes_by_participant) == 0:
            return

        vote_count = Counter(votes_by_participant.values())
        largest_nb_votes = max(vote_count.values())
        nb_votes_received = sum(vote_count.values())
        nb_remaining_votes = nb_participants - nb_votes_received

        threshold = consensus_threshold(nb_participants)

        if nb_remaining_votes + largest_nb_votes < threshold:
            raise exception_cls(
                f"cannot reach quorum={threshold}, number of remaining votes={nb_remaining_votes}, number of most voted item's votes={largest_nb_votes}"
            )

    @classmethod
    def is_majority_possible(
        cls, votes_by_participant: Dict[Any, Any], nb_participants: int
    ) -> bool:
        """
        Return true if a Byzantine majority is achievable, false otherwise.

        :param votes_by_participant: a mapping from a participant to its vote
        :param nb_participants: the total number of participants
        :return: True if the majority is still possible, false otherwise.
        """
        try:
            cls.check_majority_possible(votes_by_participant, nb_participants)
        except ABCIAppException:
            return False
        return True

    @property
    def consensus_threshold(self) -> int:
        """Consensus threshold"""
        return self._consensus_params.consensus_threshold

    @abstractmethod
    def check_payload(self, payload: BaseTxPayload) -> None:
        """Check payload."""

    @abstractmethod
    def process_payload(self, payload: BaseTxPayload) -> None:
        """Process payload."""


class DegenerateRound(AbstractRound):
    """
    This class represents the finished round during operation.

    It is a sink round.
    """

    round_id = "finished"
    allowed_tx_type = None
    payload_attribute = ""

    def check_payload(self, payload: BaseTxPayload) -> None:
        """Check payload."""
        raise NotImplementedError(  # pragma: nocover
            "DegenerateRound should not be used in operation."
        )

    def process_payload(self, payload: BaseTxPayload) -> None:
        """Process payload."""
        raise NotImplementedError(  # pragma: nocover
            "DegenerateRound should not be used in operation."
        )

    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """End block."""
        raise NotImplementedError(  # pragma: nocover
            "DegenerateRound should not be used in operation."
        )


class CollectionRound(AbstractRound):
    """
    CollectionRound.

    This class represents abstract logic for collection based rounds where
    the round object needs to collect data from different agents. The data
    might for example be from a voting round or estimation round.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize the collection round."""
        super().__init__(*args, **kwargs)
        self.collection: Dict[str, BaseTxPayload] = {}

    @property
    def payloads(self) -> List[BaseTxPayload]:
        """Get all agent payloads"""
        return list(self.collection.values())

    @property
    def payloads_count(self) -> Counter:
        """Get count of payload attributes"""
        return Counter(map(lambda p: getattr(p, self.payload_attribute), self.payloads))

    def process_payload(self, payload: BaseTxPayload) -> None:
        """Process payload."""
        if payload.round_count != self.period_state.round_count:
            raise ABCIAppInternalError(
                f"Expected round count {self.period_state.round_count} and got {payload.round_count}."
            )

        sender = payload.sender
        if sender not in self.period_state.participants:
            raise ABCIAppInternalError(
                f"{sender} not in list of participants: {sorted(self.period_state.participants)}"
            )

        if sender in self.collection:
            raise ABCIAppInternalError(
                f"sender {sender} has already sent value for round: {self.round_id}"
            )

        self.collection[sender] = payload

    def check_payload(self, payload: BaseTxPayload) -> None:
        """Check Payload"""
        if payload.round_count != self.period_state.round_count:
            raise TransactionNotValidError(
                f"Expected round count {self.period_state.round_count} and got {payload.round_count}."
            )

        sender_in_participant_set = payload.sender in self.period_state.participants
        if not sender_in_participant_set:
            raise TransactionNotValidError(
                f"{payload.sender} not in list of participants: {sorted(self.period_state.participants)}"
            )

        if payload.sender in self.collection:
            raise TransactionNotValidError(
                f"sender {payload.sender} has already sent value for round: {self.round_id}"
            )


class CollectDifferentUntilAllRound(CollectionRound):
    """
    CollectDifferentUntilAllRound

    This class represents logic for rounds where a round needs to collect
    different payloads from each agent.

    This round should only be used for registration of new agents.
    """

    def process_payload(self, payload: BaseTxPayload) -> None:
        """Process payload."""
        if payload.round_count != self.period_state.round_count:
            raise ABCIAppInternalError(
                f"Expected round count {self.period_state.round_count} and got {payload.round_count}."
            )

        if payload.sender in self.collection:
            raise ABCIAppInternalError(
                f"sender {payload.sender} has already sent value for round: {self.round_id}"
            )

        self.collection[payload.sender] = payload

    def check_payload(self, payload: BaseTxPayload) -> None:
        """Check Payload"""
        if payload.round_count != self.period_state.round_count:
            raise TransactionNotValidError(
                f"Expected round count {self.period_state.round_count} and got {payload.round_count}."
            )

        if payload.sender in self.collection:
            raise TransactionNotValidError(
                f"sender {payload.sender} has already sent value for round: {self.round_id}"
            )

    @property
    def collection_threshold_reached(
        self,
    ) -> bool:
        """Check that the collection threshold has been reached."""
        return len(self.collection) >= self._consensus_params.max_participants

    @property
    def most_voted_payload(
        self,
    ) -> Any:
        """Get the most voted payload."""
        most_voted_payload, max_votes = self.payloads_count.most_common()[0]
        if max_votes < self._consensus_params.max_participants:
            raise ABCIAppInternalError("not enough votes")
        return most_voted_payload


class CollectSameUntilThresholdRound(CollectionRound):
    """
    CollectSameUntilThresholdRound

    This class represents logic for rounds where a round needs to collect
    same payload from k of n agents.
    """

    done_event: Any
    no_majority_event: Any
    none_event: Any
    collection_key: str
    selection_key: str
    period_state_class = BasePeriodState

    @property
    def threshold_reached(
        self,
    ) -> bool:
        """Check if the threshold has been reached."""
        counts = self.payloads_count.values()
        return any(count >= self.consensus_threshold for count in counts)

    @property
    def most_voted_payload(
        self,
    ) -> Any:
        """Get the most voted payload."""
        most_voted_payload, max_votes = self.payloads_count.most_common()[0]
        if max_votes < self.consensus_threshold:
            raise ABCIAppInternalError("not enough votes")
        return most_voted_payload

    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """Process the end of the block."""
        if self.threshold_reached and self.most_voted_payload is not None:
            state = self.period_state.update(
                period_state_class=self.period_state_class,
                **{
                    self.collection_key: self.collection,
                    self.selection_key: self.most_voted_payload,
                },
            )
            return state, self.done_event
        if self.threshold_reached and self.most_voted_payload is None:
            return self.period_state, self.none_event
        if not self.is_majority_possible(
            self.collection, self.period_state.nb_participants
        ):
            return self.period_state, self.no_majority_event
        return None


class OnlyKeeperSendsRound(AbstractRound):
    """
    OnlyKeeperSendsRound

    This class represents logic for rounds where only one agent sends a
    payload
    """

    keeper_payload: Optional[Any]
    done_event: Any
    fail_event: Any
    payload_key: str
    period_state_class = BasePeriodState

    def __init__(self, *args: Any, **kwargs: Any):
        """Initialize the 'collect-observation' round."""
        super().__init__(*args, **kwargs)
        self.keeper_sent_payload = False
        self.keeper_payload: Optional[Any] = None

    def process_payload(self, payload: BaseTxPayload) -> None:  # type: ignore
        """Handle a deploy safe payload."""
        if payload.round_count != self.period_state.round_count:
            raise ABCIAppInternalError(
                f"Expected round count {self.period_state.round_count} and got {payload.round_count}."
            )

        sender = payload.sender

        if sender not in self.period_state.participants:
            raise ABCIAppInternalError(
                f"{sender} not in list of participants: {sorted(self.period_state.participants)}"
            )

        if sender != self.period_state.most_voted_keeper_address:  # type: ignore
            raise ABCIAppInternalError(f"{sender} not elected as keeper.")

        if self.keeper_sent_payload:
            raise ABCIAppInternalError("keeper already set the payload.")

        self.keeper_payload = getattr(payload, self.payload_attribute)
        self.keeper_sent_payload = True

    def check_payload(self, payload: BaseTxPayload) -> None:  # type: ignore
        """Check a deploy safe payload can be applied to the current state."""
        if payload.round_count != self.period_state.round_count:
            raise TransactionNotValidError(
                f"Expected round count {self.period_state.round_count} and got {payload.round_count}."
            )

        sender = payload.sender
        sender_in_participant_set = sender in self.period_state.participants
        if not sender_in_participant_set:
            raise TransactionNotValidError(
                f"{sender} not in list of participants: {sorted(self.period_state.participants)}"
            )

        sender_is_elected_sender = sender == self.period_state.most_voted_keeper_address  # type: ignore
        if not sender_is_elected_sender:
            raise TransactionNotValidError(f"{sender} not elected as keeper.")

        if self.keeper_sent_payload:
            raise TransactionNotValidError("keeper payload value already set.")

    @property
    def has_keeper_sent_payload(
        self,
    ) -> bool:
        """Check if keeper has sent the payload."""

        return self.keeper_sent_payload

    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """Process the end of the block."""
        # if reached participant threshold, set the result
        if self.has_keeper_sent_payload and self.keeper_payload is not None:
            state = self.period_state.update(
                period_state_class=self.period_state_class,
                **{self.payload_key: self.keeper_payload},
            )
            return state, self.done_event
        if self.has_keeper_sent_payload and self.keeper_payload is None:
            return self.period_state, self.fail_event
        return None


class VotingRound(CollectionRound):
    """
    VotingRound

    This class represents logic for rounds where a round needs votes from
    agents, pass if k same votes of n agents
    """

    done_event: Any
    negative_event: Any
    none_event: Any
    no_majority_event: Any
    collection_key: str
    period_state_class = BasePeriodState

    @property
    def vote_count(self) -> Counter:
        """Get agent payload vote count"""
        return Counter(payload.vote for payload in self.collection.values())  # type: ignore

    @property
    def positive_vote_threshold_reached(self) -> bool:
        """Check that the vote threshold has been reached."""
        return self.vote_count[True] >= self.consensus_threshold

    @property
    def negative_vote_threshold_reached(self) -> bool:
        """Check that the vote threshold has been reached."""
        return self.vote_count[False] >= self.consensus_threshold

    @property
    def none_vote_threshold_reached(self) -> bool:
        """Check that the vote threshold has been reached."""
        return self.vote_count[None] >= self.consensus_threshold

    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """Process the end of the block."""
        # if reached participant threshold, set the result
        if self.positive_vote_threshold_reached:
            state = self.period_state.update(
                period_state_class=self.period_state_class,
                **{self.collection_key: self.collection},  # type: ignore
            )
            return state, self.done_event
        if self.negative_vote_threshold_reached:
            return self.period_state, self.negative_event
        if self.none_vote_threshold_reached:
            return self.period_state, self.none_event
        if not self.is_majority_possible(
            self.collection, self.period_state.nb_participants
        ):
            return self.period_state, self.no_majority_event
        return None


class CollectDifferentUntilThresholdRound(CollectionRound):
    """
    CollectDifferentUntilThresholdRound

    This class represents logic for rounds where a round needs to collect
    different payloads from k of n agents
    """

    done_event: Any
    no_majority_event: Any
    selection_key: str
    collection_key: str
    required_block_confirmations: int = 0
    period_state_class = BasePeriodState

    @property
    def collection_threshold_reached(
        self,
    ) -> bool:
        """Check if the threshold has been reached."""
        return len(self.collection) >= self.consensus_threshold

    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """Process the end of the block."""
        if self.collection_threshold_reached:
            self.block_confirmations += 1
        if (  # contracts are set from previous rounds
            self.collection_threshold_reached
            and self.block_confirmations > self.required_block_confirmations
            # we also wait here as it gives more (available) agents time to join
        ):
            state = self.period_state.update(
                period_state_class=self.period_state_class,
                period_count=None,
                **{
                    self.selection_key: frozenset(list(self.collection.keys())),
                    self.collection_key: self.collection,
                },
            )
            return state, self.done_event
        if not self.is_majority_possible(
            self.collection, self.period_state.nb_participants
        ):
            return self.period_state, self.no_majority_event
        return None


class CollectNonEmptyUntilThresholdRound(CollectDifferentUntilThresholdRound):
    """
    Collect all the data among agents.

    This class represents logic for rounds where we need to collect
    payloads from each agent which will contain optional, different data and only keep the non-empty.

    This round may be used for cases that we want to collect all the agent's data, such as late-arriving messages.
    """

    none_event: Any

    def _get_non_empty_values(self) -> List:
        """Get the non-empty values from the payload, for the given attribute."""
        non_empty_values = []

        for payload in self.collection.values():
            attribute_value = getattr(payload, self.payload_attribute, None)
            if attribute_value is not None:
                non_empty_values.append(attribute_value)

        return non_empty_values

    def end_block(self) -> Optional[Tuple[BasePeriodState, Enum]]:
        """Process the end of the block."""
        if self.collection_threshold_reached:
            self.block_confirmations += 1
        if (
            self.collection_threshold_reached
            and self.block_confirmations > self.required_block_confirmations
        ):
            non_empty_values = self._get_non_empty_values()

            state = self.period_state.update(
                period_state_class=self.period_state_class,
                period_count=None,
                **{
                    self.selection_key: frozenset(list(self.collection.keys())),
                    self.collection_key: non_empty_values,
                },
            )

            if len(non_empty_values) == 0:
                return state, self.none_event
            return state, self.done_event

        if not self.is_majority_possible(
            self.collection, self.period_state.nb_participants
        ):
            return self.period_state, self.no_majority_event
        return None


AppState = Type[AbstractRound]
AbciAppTransitionFunction = Dict[AppState, Dict[EventType, AppState]]
EventToTimeout = Dict[EventType, float]


@dataclass(order=True)
class TimeoutEvent(Generic[EventType]):
    """Timeout event."""

    deadline: datetime.datetime
    entry_count: int
    event: EventType = field(compare=False)
    cancelled: bool = field(default=False, compare=False)


class Timeouts(Generic[EventType]):
    """Class to keep track of pending timeouts."""

    def __init__(self) -> None:
        """Initialize."""
        # The entry count serves as a tie-breaker so that two tasks with
        # the same priority are returned in the order they were added
        self._counter = itertools.count()

        # The timeout priority queue keeps the earliest deadline at the top.
        self._heap: List[TimeoutEvent[EventType]] = []

        # Mapping from entry id to task
        self._entry_finder: Dict[int, TimeoutEvent[EventType]] = {}

    @property
    def size(self) -> int:
        """Get the size of the timeout queue."""
        return len(self._heap)

    def add_timeout(self, deadline: datetime.datetime, event: EventType) -> int:
        """Add a timeout."""
        entry_count = next(self._counter)
        timeout_event = TimeoutEvent[EventType](deadline, entry_count, event)
        heapq.heappush(self._heap, timeout_event)
        self._entry_finder[entry_count] = timeout_event
        return entry_count

    def cancel_timeout(self, entry_count: int) -> None:
        """
        Remove a timeout.

        :param entry_count: the entry id to remove.
        :raises: KeyError: if the entry count is not found.
        """
        if entry_count in self._entry_finder:
            self._entry_finder[entry_count].cancelled = True

    def pop_earliest_cancelled_timeouts(self) -> None:
        """Pop earliest cancelled timeouts."""
        if self.size == 0:
            return
        entry = self._heap[0]  # heap peak
        while entry.cancelled:
            self.pop_timeout()
            if self.size == 0:
                break
            entry = self._heap[0]

    def get_earliest_timeout(self) -> Tuple[datetime.datetime, Any]:
        """Get the earliest timeout-event pair."""
        entry = self._heap[0]
        return entry.deadline, entry.event

    def pop_timeout(self) -> Tuple[datetime.datetime, Any]:
        """Remove and return the earliest timeout-event pair."""
        entry = heapq.heappop(self._heap)
        del self._entry_finder[entry.entry_count]
        return entry.deadline, entry.event


class _MetaAbciApp(ABCMeta):
    """A metaclass that validates AbciApp's attributes."""

    def __new__(mcs, name: str, bases: Tuple, namespace: Dict, **kwargs: Any) -> Type:  # type: ignore
        """Initialize the class."""
        new_cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        if ABC in bases:
            # abstract class, return
            return new_cls
        if not issubclass(new_cls, AbciApp):
            # the check only applies to AbciApp subclasses
            return new_cls

        mcs._check_consistency(cast(Type[AbciApp], new_cls))
        return new_cls

    @classmethod
    def _check_consistency(mcs, abci_app_cls: Type["AbciApp"]) -> None:
        """Check consistency of class attributes."""
        mcs._check_required_class_attributes(abci_app_cls)
        mcs._check_initial_states_and_final_states(abci_app_cls)
        mcs._check_consistency_outgoing_transitions_from_non_final_states(abci_app_cls)

    @classmethod
    def _check_required_class_attributes(mcs, abci_app_cls: Type["AbciApp"]) -> None:
        """Check that required class attributes are set."""
        if not hasattr(abci_app_cls, "initial_round_cls"):
            raise ABCIAppInternalError("'initial_round_cls' field not set")
        if not hasattr(abci_app_cls, "transition_function"):
            raise ABCIAppInternalError("'transition_function' field not set")

    @classmethod
    def _check_initial_states_and_final_states(
        mcs,
        abci_app_cls: Type["AbciApp"],
    ) -> None:
        """
        Check that initial states and final states are consistent.

        I.e.:
        - check that all the initial states are in the set of states specified
          by the transition function.
        - check that the initial state has outgoing transitions
        - check that the initial state does not trigger timeout events. This is
          because we need at least one block/timestamp to start timeouts.
        - check that initial states are not final states.
        - check that the set of final states is a proper subset of the set of
          states.
        - check that a final state does not have outgoing transitions.

        :param abci_app_cls: the AbciApp class
        """
        initial_round_cls = abci_app_cls.initial_round_cls
        initial_states = abci_app_cls.initial_states
        transition_function = abci_app_cls.transition_function
        final_states = abci_app_cls.final_states
        states = abci_app_cls.get_all_rounds()

        enforce(
            initial_states == set() or initial_round_cls in initial_states,
            f"initial round class {initial_round_cls} is not in the set of "
            f"initial states: {initial_states}",
        )
        enforce(
            initial_round_cls in states
            and all(initial_state in states for initial_state in initial_states),
            "initial states must be in the set of states",
        )

        true_initial_states = (
            initial_states if initial_states != set() else {initial_round_cls}
        )
        enforce(
            all(
                initial_state not in final_states
                for initial_state in true_initial_states
            ),
            "initial states cannot be final states",
        )

        unknown_final_states = set.difference(final_states, states)
        enforce(
            len(unknown_final_states) == 0,
            f"the following final states are not in the set of states:"
            f" {unknown_final_states}",
        )

        enforce(
            all(
                len(transition_function[final_state]) == 0
                for final_state in final_states
            ),
            "final states cannot have outgoing transitions",
        )

        enforce(
            all(
                issubclass(final_state, DegenerateRound) for final_state in final_states
            ),
            "final round classes must be subclasses of the DegenerateRound class",
        )

    @classmethod
    def _check_consistency_outgoing_transitions_from_non_final_states(
        mcs, abci_app_cls: Type["AbciApp"]
    ) -> None:
        """
        Check consistency of outgoing transitions from non-final states.

        In particular, check that all non-final states have:
        - at least one non-timeout transition.
        - at most one timeout transition

        :param abci_app_cls: the AbciApp class
        """
        states = abci_app_cls.get_all_rounds()
        event_to_timeout = abci_app_cls.event_to_timeout

        non_final_states = states.difference(abci_app_cls.final_states)
        timeout_events = set(event_to_timeout.keys())
        for non_final_state in non_final_states:
            outgoing_transitions = abci_app_cls.transition_function[non_final_state]

            outgoing_events = set(outgoing_transitions.keys())
            outgoing_timeout_events = set.intersection(outgoing_events, timeout_events)
            outgoing_nontimeout_events = set.difference(outgoing_events, timeout_events)

            enforce(
                len(outgoing_timeout_events) < 2,
                f"non-final state {non_final_state} cannot have more than one "
                f"outgoing timeout event, got: "
                f"{', '.join(map(str, outgoing_timeout_events))}",
            )
            enforce(
                len(outgoing_nontimeout_events) > 0,
                f"non-final state {non_final_state} must have at least one "
                f"non-timeout transition",
            )


class AbciApp(
    Generic[EventType], ABC, metaclass=_MetaAbciApp
):  # pylint: disable=too-many-instance-attributes
    """
    Base class for ABCI apps.

    Concrete classes of this class implement the ABCI App.
    """

    initial_round_cls: AppState
    initial_states: Set[AppState] = set()
    transition_function: AbciAppTransitionFunction
    final_states: Set[AppState] = set()
    event_to_timeout: EventToTimeout = {}
    cross_period_persisted_keys: List[str] = []

    def __init__(
        self,
        state: BasePeriodState,
        consensus_params: ConsensusParams,
        logger: logging.Logger,
    ):
        """Initialize the AbciApp."""
        self._initial_state = state
        self.consensus_params = consensus_params
        self.logger = logger

        self._current_round_cls: Optional[AppState] = None
        self._current_round: Optional[AbstractRound] = None
        self._last_round: Optional[AbstractRound] = None
        self._previous_rounds: List[AbstractRound] = []
        self._current_round_height: int = 0
        self._round_results: List[BasePeriodState] = []
        self._last_timestamp: Optional[datetime.datetime] = None
        self._current_timeout_entries: List[int] = []
        self._timeouts = Timeouts[EventType]()

    @property
    def state(self) -> BasePeriodState:
        """Return the current state."""
        latest_result = self.latest_result
        return latest_result if latest_result is not None else self._initial_state

    @classmethod
    def get_all_rounds(cls) -> Set[AppState]:
        """Get all the round states."""
        return set(cls.transition_function)

    @classmethod
    def get_all_events(cls) -> Set[EventType]:
        """Get all the events."""
        events: Set[EventType] = set()
        for _, transitions in cls.transition_function.items():
            events.update(transitions.keys())
        return events

    @classmethod
    def get_all_round_classes(cls) -> Set[AppState]:
        """Get all round classes."""
        result: Set[AppState] = set()
        for start, transitions in cls.transition_function.items():
            result.add(start)
            result.update(transitions.values())
        return result

    @property
    def last_timestamp(self) -> datetime.datetime:
        """Get last timestamp."""
        if self._last_timestamp is None:
            raise ABCIAppInternalError("last timestamp is None")
        return self._last_timestamp

    def setup(self) -> None:
        """Set up the behaviour."""
        self._schedule_round(self.initial_round_cls)

    def _log_start(self) -> None:
        """Log the entering in the round."""
        self.logger.info(
            f"Entered in the '{self.current_round.round_id}' round for period "
            f"{self.state.period_count}"
        )

    def _log_end(self, event: EventType) -> None:
        """Log the exiting from the round."""
        self.logger.info(
            f"'{self.current_round.round_id}' round is done with event: {event}"
        )

    def _extend_previous_rounds_with_current_round(self) -> None:
        self._previous_rounds.append(self.current_round)
        self._current_round_height += 1

    def _schedule_round(self, round_cls: AppState) -> None:
        """
        Schedule a round class.

        this means:
        - cancel timeout events belonging to the current round;
        - instantiate the new round class and set it as current round;
        - create new timeout events and schedule them according to the latest
          timestamp.

        :param round_cls: the class of the new round.
        """
        self.logger.debug("scheduling new round: %s", round_cls)
        for entry_id in self._current_timeout_entries:
            self._timeouts.cancel_timeout(entry_id)

        self._current_timeout_entries = []
        next_events = list(self.transition_function.get(round_cls, {}).keys())
        for event in next_events:
            timeout = self.event_to_timeout.get(event, None)
            # if first round, last_timestamp is None.
            # This means we do not schedule timeout events,
            # but we allow timeout events from the initial state
            # in case of concatenation.
            if timeout is not None and self._last_timestamp is not None:
                # last timestamp can be in the past relative to last seen block
                # time if we're scheduling from within update_time
                deadline = self.last_timestamp + datetime.timedelta(0, timeout)
                entry_id = self._timeouts.add_timeout(deadline, event)
                self.logger.info(
                    "scheduling timeout of %s seconds for event %s with deadline %s",
                    timeout,
                    event,
                    deadline,
                )
                self._current_timeout_entries.append(entry_id)

        # self.state will point to last result,
        # or if not available to the initial state
        last_result = (
            self._round_results[-1]
            if len(self._round_results) > 0
            else self._initial_state
        )
        self._last_round = self._current_round
        self._current_round_cls = round_cls
        self._current_round = round_cls(
            last_result,
            self.consensus_params,
            (
                self._last_round.allowed_tx_type
                if self._last_round is not None
                and self._last_round.allowed_tx_type
                != self._current_round_cls.allowed_tx_type
                # when transitioning to a round with the same payload type we set None as otherwise it will allow no tx to be sumitted
                else None
            ),
        )
        self._log_start()
        self.state.db.increment_round_count()

    @property
    def current_round(self) -> AbstractRound:
        """Get the current round."""
        if self._current_round is None:
            raise ValueError("current_round not set!")
        return self._current_round

    @property
    def current_round_id(self) -> Optional[str]:
        """Get the current round id."""
        return self._current_round.round_id if self._current_round else None

    @property
    def current_round_height(self) -> int:
        """Get the current round height."""
        return self._current_round_height

    @property
    def last_round_id(self) -> Optional[str]:
        """Get the last round id."""
        return self._last_round.round_id if self._last_round else None

    @property
    def is_finished(self) -> bool:
        """Check whether the AbciApp execution has finished."""
        return self._current_round is None

    @property
    def latest_result(self) -> Optional[BasePeriodState]:
        """Get the latest result of the round."""
        return None if len(self._round_results) == 0 else self._round_results[-1]

    def check_transaction(self, transaction: Transaction) -> None:
        """
        Check a transaction.

        Forward the call to the current round object.

        :param transaction: the transaction.
        """
        self.current_round.check_transaction(transaction)

    def process_transaction(self, transaction: Transaction) -> None:
        """
        Process a transaction.

        Forward the call to the current round object.

        :param transaction: the transaction.
        """
        self.current_round.process_transaction(transaction)

    def process_event(
        self, event: EventType, result: Optional[BasePeriodState] = None
    ) -> None:
        """Process a round event."""
        if self._current_round_cls is None:
            self.logger.info(
                f"cannot process event '{event}' as current state is not set"
            )
            return

        next_round_cls = self.transition_function[self._current_round_cls].get(
            event, None
        )
        self._extend_previous_rounds_with_current_round()
        if result is not None:
            self._round_results.append(result)
        else:
            # we duplicate the state since the round was preemptively ended
            self._round_results.append(self.current_round.period_state)

        self._log_end(event)
        if next_round_cls is not None:
            self._schedule_round(next_round_cls)
        else:
            self.logger.warning("AbciApp has reached a dead end.")
            self._current_round_cls = None
            self._current_round = None

    def update_time(self, timestamp: datetime.datetime) -> None:
        """
        Observe timestamp from last block.

        :param timestamp: the latest block's timestamp.
        """
        self.logger.info("arrived block with timestamp: %s", timestamp)
        self.logger.info("current AbciApp time: %s", self._last_timestamp)
        self._timeouts.pop_earliest_cancelled_timeouts()

        if self._timeouts.size == 0:
            # if no pending timeouts, then it is safe to
            # move forward the last known timestamp to the
            # latest block's timestamp.
            self.logger.info("no pending timeout, move time forward")
            self._last_timestamp = timestamp
            return

        earliest_deadline, _ = self._timeouts.get_earliest_timeout()
        while earliest_deadline <= timestamp:
            # the earliest deadline is expired. Pop it from the
            # priority queue and process the timeout event.
            expired_deadline, timeout_event = self._timeouts.pop_timeout()
            self.logger.warning(
                "expired deadline %s with event %s at AbciApp time %s",
                expired_deadline,
                timeout_event,
                timestamp,
            )

            # the last timestamp now becomes the expired deadline
            # clearly, it is earlier than the current highest known
            # timestamp that comes from the consensus engine.
            # However, we need it to correctly simulate the timeouts
            # of the next rounds. (for now we set it to timestamp to explore
            # the impact)
            self._last_timestamp = timestamp
            self.logger.info(
                "current AbciApp time after expired deadline: %s", self.last_timestamp
            )

            self.process_event(timeout_event)

            self._timeouts.pop_earliest_cancelled_timeouts()
            if self._timeouts.size == 0:
                break
            earliest_deadline, _ = self._timeouts.get_earliest_timeout()

        # at this point, there is no timeout event left to be triggered,
        # so it is safe to move forward the last known timestamp to the
        # new block's timestamp
        self._last_timestamp = timestamp
        self.logger.debug("final AbciApp time: %s", self._last_timestamp)

    def cleanup(self, cleanup_history_depth: int) -> None:
        """Clear data."""
        if len(self._round_results) != len(self._previous_rounds):
            raise ABCIAppInternalError("Inconsistent round lengths")  # pragma: nocover
        # we need at least the last round result, and for symmetry we impose the same condition
        # on previous rounds and state.db
        cleanup_history_depth = max(cleanup_history_depth, MIN_HISTORY_DEPTH)
        self._previous_rounds = self._previous_rounds[-cleanup_history_depth:]
        self._round_results = self._round_results[-cleanup_history_depth:]
        self.state.db.cleanup(cleanup_history_depth)


class Period:
    """
    This class represents a period (i.e. a sequence of rounds)

    It is a generic class that keeps track of the current round
    of the consensus period. It receives 'deliver_tx' requests
    from the ABCI handlers and forwards them to the current
    active round instance, which implements the ABCI app logic.
    It also schedules the next round (if any) whenever a round terminates.
    """

    class _BlockConstructionState(Enum):
        """
        Phases of an ABCI-based block construction.

        WAITING_FOR_BEGIN_BLOCK: the app is ready to accept
            "begin_block" requests from the consensus engine node.
            Then, it transitions into the 'WAITING_FOR_DELIVER_TX' phase.
        WAITING_FOR_DELIVER_TX: the app is building the block
            by accepting "deliver_tx" requests, and waits
            until the "end_block" request.
            Then, it transitions into the 'WAITING_FOR_COMMIT' phase.
        WAITING_FOR_COMMIT: the app finished the construction
            of the block, but it is waiting for the "commit"
            request from the consensus engine node.
            Then, it transitions into the 'WAITING_FOR_BEGIN_BLOCK' phase.
        """

        WAITING_FOR_BEGIN_BLOCK = "waiting_for_begin_block"
        WAITING_FOR_DELIVER_TX = "waiting_for_deliver_tx"
        WAITING_FOR_COMMIT = "waiting_for_commit"

    def __init__(self, abci_app_cls: Type[AbciApp]):
        """Initialize the round."""
        self._blockchain = Blockchain()
        self._syncing_up = True

        self._block_construction_phase = (
            Period._BlockConstructionState.WAITING_FOR_BEGIN_BLOCK
        )

        self._block_builder = BlockBuilder()
        self._abci_app_cls = abci_app_cls
        self._abci_app: Optional[AbciApp] = None

    def setup(self, *args: Any, **kwargs: Any) -> None:
        """
        Set up the period.

        :param args: the arguments to pass to the round constructor.
        :param kwargs: the keyword-arguments to pass to the round constructor.
        """
        self._abci_app = self._abci_app_cls(*args, **kwargs)
        self._abci_app.setup()

    def start_sync(
        self,
    ) -> None:  # pragma: nocover
        """
        Set `_syncing_up` flag to true.

        if the _syncing_up flag is set to true, the `async_act` method won't be executed. For more details refer to
        https://github.com/valory-xyz/consensus-algorithms/issues/247#issuecomment-1012268656
        """
        self._syncing_up = True

    def end_sync(
        self,
    ) -> None:
        """Set `_syncing_up` flag to false."""
        self._syncing_up = False

    @property
    def syncing_up(
        self,
    ) -> bool:
        """Return if the app is in sync mode."""
        return self._syncing_up

    @property
    def abci_app(self) -> AbciApp:
        """Get the AbciApp."""
        if self._abci_app is None:
            raise ABCIAppInternalError("AbciApp not set")  # pragma: nocover
        return self._abci_app

    @property
    def height(self) -> int:
        """Get the height."""
        return self._blockchain.height

    @property
    def is_finished(self) -> bool:
        """Check if a period has finished."""
        return self.abci_app.is_finished

    def check_is_finished(self) -> None:
        """Check if a period has finished."""
        if self.is_finished:
            raise ValueError("period is finished, cannot accept new transactions")

    @property
    def current_round(self) -> AbstractRound:
        """Get current round."""
        return self.abci_app.current_round

    @property
    def current_round_id(self) -> Optional[str]:
        """Get the current round id."""
        return self.abci_app.current_round_id

    @property
    def current_round_height(self) -> int:
        """Get the current round height."""
        return self.abci_app.current_round_height

    @property
    def last_round_id(self) -> Optional[str]:
        """Get the last round id."""
        return self.abci_app.last_round_id

    @property
    def last_timestamp(self) -> datetime.datetime:
        """Get the last timestamp."""
        last_timestamp = (
            self._blockchain.blocks[-1].timestamp
            if self._blockchain.length != 0
            else None
        )
        if last_timestamp is None:
            raise ABCIAppInternalError("last timestamp is None")
        return last_timestamp

    @property
    def latest_state(self) -> BasePeriodState:
        """Get the latest state."""
        return self.abci_app.state

    def begin_block(self, header: Header) -> None:
        """Begin block."""
        if self.is_finished:
            raise ABCIAppInternalError("period is finished, cannot accept new blocks")
        if (
            self._block_construction_phase
            != Period._BlockConstructionState.WAITING_FOR_BEGIN_BLOCK
        ):
            raise ABCIAppInternalError(
                f"cannot accept a 'begin_block' request. Current phase={self._block_construction_phase}"
            )

        # From now on, the ABCI app waits for 'deliver_tx' requests, until 'end_block' is received
        self._block_construction_phase = (
            Period._BlockConstructionState.WAITING_FOR_DELIVER_TX
        )
        self._block_builder.reset()
        self._block_builder.header = header
        self.abci_app.update_time(header.timestamp)

    def deliver_tx(self, transaction: Transaction) -> None:
        """
        Deliver a transaction.

        Appends the transaction to build the block on 'end_block' later.
        :param transaction: the transaction.
        :raises:  an Error otherwise.
        """
        if (
            self._block_construction_phase
            != Period._BlockConstructionState.WAITING_FOR_DELIVER_TX
        ):
            raise ABCIAppInternalError(
                f"cannot accept a 'deliver_tx' request. Current phase={self._block_construction_phase}"
            )

        self.abci_app.check_transaction(transaction)
        self.abci_app.process_transaction(transaction)
        self._block_builder.add_transaction(transaction)

    def end_block(self) -> None:
        """Process the 'end_block' request."""
        if (
            self._block_construction_phase
            != Period._BlockConstructionState.WAITING_FOR_DELIVER_TX
        ):
            raise ABCIAppInternalError(
                f"cannot accept a 'end_block' request. Current phase={self._block_construction_phase}"
            )
        # The ABCI app waits for the commit
        self._block_construction_phase = (
            Period._BlockConstructionState.WAITING_FOR_COMMIT
        )

    def commit(self) -> None:
        """Process the 'commit' request."""
        if (
            self._block_construction_phase
            != Period._BlockConstructionState.WAITING_FOR_COMMIT
        ):
            raise ABCIAppInternalError(
                f"cannot accept a 'commit' request. Current phase={self._block_construction_phase}"
            )
        block = self._block_builder.get_block()
        try:
            self._blockchain.add_block(block)
            self._update_round()
            # The ABCI app now waits again for the next block
            self._block_construction_phase = (
                Period._BlockConstructionState.WAITING_FOR_BEGIN_BLOCK
            )
        except AddBlockError as exception:
            raise exception

    def reset_blockchain(self, is_replay: bool = False) -> None:
        """Reset blockchain after tendermint reset."""
        if is_replay:
            self._block_construction_phase = (
                Period._BlockConstructionState.WAITING_FOR_BEGIN_BLOCK
            )
        self._blockchain = Blockchain()

    def _update_round(self) -> None:
        """
        Update a round.

        Check whether the round has finished. If so, get the
        new round and set it as the current round.
        """
        result: Optional[Tuple[BasePeriodState, Any]] = self.current_round.end_block()
        if result is None:
            return
        round_result, event = result
        _logger.debug(
            f"updating round, current_round {self.current_round.round_id}, event: {event}, round result {round_result}"
        )
        self.abci_app.process_event(event, result=round_result)
