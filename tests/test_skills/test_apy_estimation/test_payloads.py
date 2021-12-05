# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021 Valory AG
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

"""Test the payloads.py module of the skill."""

from packages.valory.skills.apy_estimation.payloads import (
    EstimatePayload,
    FetchingPayload,
    OptimizationPayload,
    PreprocessPayload,
    RandomnessPayload,
    ResetPayload,
    TestingPayload,
    TrainingPayload,
    TransactionType,
    TransformationPayload,
)


class TestTransactionType:
    """Test for `TransactionType`."""

    def test__str__(self) -> None:
        """Test `__str__`."""
        for transaction_type in TransactionType:
            assert transaction_type.value == str(transaction_type)


class TestPayloads:
    """Test for `Payloads`."""

    @staticmethod
    def test_fetching_payload() -> None:
        """Test `FetchingPayload`"""
        payload = FetchingPayload(sender="sender", history_hash="x0", id_="id")

        assert payload.transaction_type == TransactionType.FETCHING
        assert payload.history == "x0"
        assert payload.id_ == "id"
        assert payload.data == {"history": "x0"}

    @staticmethod
    def test_transformation_payload() -> None:
        """Test `TransformationPayload`"""
        payload = TransformationPayload(
            sender="sender", transformation_hash="x0", id_="id"
        )

        assert payload.transaction_type == TransactionType.TRANSFORMATION
        assert payload.transformation == "x0"
        assert payload.id_ == "id"
        assert payload.data == {"transformation": "x0"}

    @staticmethod
    def test_preprocess_payload() -> None:
        """Test `PreprocessPayload`"""
        payload = PreprocessPayload(
            sender="sender", train_hash="x0", test_hash="x1", pair_name="test", id_="id"
        )

        assert payload.transaction_type == TransactionType.PREPROCESS
        assert payload.train_test_hash == "x0x1"
        assert payload.pair_name == "test"
        assert payload.id_ == "id"
        assert payload.data == {"train_test": "x0x1", "pair_name": "test"}

    @staticmethod
    def test_randomness_payload() -> None:
        """Test `RandomnessPayload`"""

        payload = RandomnessPayload(
            sender="sender", round_id=1, randomness="1", id_="id"
        )

        assert payload.round_id == 1
        assert payload.randomness == "1"
        assert payload.id_ == "id"
        assert payload.data == {"round_id": 1, "randomness": "1"}

        assert payload.transaction_type == TransactionType.RANDOMNESS

    @staticmethod
    def test_optimization_payload() -> None:
        """Test `OptimizationPayload`"""
        payload = OptimizationPayload(
            sender="sender",
            study_hash="x0",
            best_params={"test": 2.0421833357796},
            id_="id",
        )

        assert payload.transaction_type == TransactionType.OPTIMIZATION
        assert payload.study == "x0"
        assert payload.best_params == {"test": 2.0421833357796}
        assert payload.id_ == "id"
        assert payload.data == {
            "study_hash": "x0",
            "best_params": {"test": 2.0421833357796},
        }

    @staticmethod
    def test_training_payload() -> None:
        """Test `TrainingPayload`"""
        payload = TrainingPayload(sender="sender", model_hash="x0", id_="id")

        assert payload.transaction_type == TransactionType.TRAINING
        assert payload.model == "x0"
        assert payload.id_ == "id"
        assert payload.data == {"model_hash": "x0"}

    @staticmethod
    def test_testing_payload() -> None:
        """Test `TestingPayload`"""
        payload = TestingPayload(sender="sender", report_hash="x0", id_="id")

        assert payload.transaction_type == TransactionType.TESTING
        assert payload.report_hash == "x0"
        assert payload.id_ == "id"
        assert payload.data == {"report_hash": "x0"}

    @staticmethod
    def test_estimate_payload() -> None:
        """Test `EstimatePayload`"""
        payload = EstimatePayload(
            sender="sender", estimation=[2.0044, 5.8365], id_="id"
        )

        assert payload.transaction_type == TransactionType.ESTIMATION
        assert payload.estimation == [2.0044, 5.8365]
        assert payload.id_ == "id"
        assert payload.data == {"estimation": [2.0044, 5.8365]}

    @staticmethod
    def test_reset_payload() -> None:
        """Test `ResetPayload`"""
        payload = ResetPayload(sender="sender", period_count=0, id_="id")

        assert payload.transaction_type == TransactionType.RESET
        assert payload.period_count == 0
        assert payload.id_ == "id"
        assert payload.data == {"period_count": 0}