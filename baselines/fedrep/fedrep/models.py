"""Abstract class for splitting a model into body and head."""

import os
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
from omegaconf import DictConfig
from torch import Tensor
from torch.utils.data import DataLoader

from fedrep.constants import (
    DEFAULT_FINETUNE_EPOCHS,
    DEFAULT_LOCAL_TRAIN_EPOCHS,
    DEFAULT_REPRESENTATION_EPOCHS,
)


class ModelSplit(ABC, nn.Module):
    """Abstract class for splitting a model into body and head."""

    def __init__(self, model: nn.Module):
        """Initialize the attributes of the model split.

        Args:
            model: dict containing the vocab sizes of the input attributes.
        """
        super().__init__()

        self._body, self._head = self._get_model_parts(model)

    @abstractmethod
    def _get_model_parts(self, model: nn.Module) -> Tuple[nn.Module, nn.Module]:
        """Return the body and head of the model.

        Args:
            model: model to be split into head and body

        Returns
        -------
            Tuple where the first element is the body of the model
            and the second is the head.
        """

    @property
    def body(self) -> nn.Module:
        """Return model body."""
        return self._body

    @body.setter
    def body(self, state_dict: "OrderedDict[str, Tensor]") -> None:
        """Set model body.

        Args:
            state_dict: dictionary of the state to set the model body to.
        """
        self.body.load_state_dict(state_dict, strict=True)

    @property
    def head(self) -> nn.Module:
        """Return model head."""
        return self._head

    @head.setter
    def head(self, state_dict: "OrderedDict[str, Tensor]") -> None:
        """Set model head.

        Args:
            state_dict: dictionary of the state to set the model head to.
        """
        self.head.load_state_dict(state_dict, strict=True)

    def get_parameters(self) -> List[np.ndarray]:
        """Get model parameters (without fixed head).

        Returns
        -------
            Body and head parameters
        """
        return [
            val.cpu().numpy()
            for val in [
                *self.body.state_dict().values(),
                *self.head.state_dict().values(),
            ]
        ]

    def set_parameters(self, state_dict: Dict[str, Tensor]) -> None:
        """Set model parameters.

        Args:
            state_dict: dictionary of the state to set the model to.
        """
        ordered_state_dict = OrderedDict(self.state_dict().copy())
        # Update with the values of the state_dict
        ordered_state_dict.update(dict(state_dict.items()))
        self.load_state_dict(ordered_state_dict, strict=False)

    def enable_head(self) -> None:
        """Enable gradient tracking for the head parameters."""
        for param in self.head.parameters():
            param.requires_grad = True

    def enable_body(self) -> None:
        """Enable gradient tracking for the body parameters."""
        for param in self.body.parameters():
            param.requires_grad = True

    def disable_head(self) -> None:
        """Disable gradient tracking for the head parameters."""
        for param in self.head.parameters():
            param.requires_grad = False

    def disable_body(self) -> None:
        """Disable gradient tracking for the body parameters."""
        for param in self.body.parameters():
            param.requires_grad = False

    def forward(self, inputs: Any) -> Any:
        """Forward inputs through the body and the head."""
        x = self.body(inputs)
        return self.head(x)


# pylint: disable=R0902
class ModelManager(ABC):
    """Manager for models with Body/Head split."""

    # pylint: disable=R0913
    def __init__(
        self,
        client_id: int,
        config: DictConfig,
        trainloader: DataLoader,
        testloader: DataLoader,
        client_save_path: Optional[str],
        learning_rate: float,
        model_split_class: Any,
    ):
        """Initialize the attributes of the model manager.

        Args:
            client_id: The id of the client.
            config: Dict containing the configurations to be used by the manager.
            model_split_class: Class to be used to split the model into body and head\
                (concrete implementation of ModelSplit).
        """
        super().__init__()
        self.config = config
        self.client_id = client_id
        self.trainloader = trainloader
        self.testloader = testloader
        self.device = self.config.server_device
        self.client_save_path = client_save_path
        self.learning_rate = learning_rate
        self._model: ModelSplit = model_split_class(self._create_model())

    @abstractmethod
    def _create_model(self) -> nn.Module:
        """Return model to be splitted into head and body."""

    @property
    def model(self) -> nn.Module:
        """Return model."""
        return self._model

    def train(self) -> Dict[str, Union[List[Dict[str, float]], int, float]]:
        """Train the model maintained in self.model.

        Method adapted from simple CNNCifar10-v1 (PyTorch) \
        https://github.com/wjc852456/pytorch-cnncifar10net-v1.

        Args:
            epochs: number of training epochs.

        Returns
        -------
            Dict containing the train metrics.
        """
        # Load client state (head) if client_save_path is not None and it is not empty
        if self.client_save_path is not None and os.path.isfile(self.client_save_path):
            self.model.head.load_state_dict(torch.load(self.client_save_path))

        num_local_epochs = DEFAULT_LOCAL_TRAIN_EPOCHS
        if hasattr(self.config, "num_local_epochs"):
            num_local_epochs = int(self.config.num_local_epochs)

        num_rep_epochs = DEFAULT_REPRESENTATION_EPOCHS
        if hasattr(self.config, "num_rep_epochs"):
            num_rep_epochs = int(self.config.num_rep_epochs)

        criterion = torch.nn.CrossEntropyLoss()
        optimizer = torch.optim.SGD(
            self.model.parameters(), lr=self.learning_rate, momentum=0.5
        )
        correct, total = 0, 0
        loss: torch.Tensor = 0.0

        self.model.train()
        for i in range(num_local_epochs + num_rep_epochs):
            if i < num_local_epochs:
                self.model.disable_body()
                self.model.enable_head()
            else:
                self.model.enable_body()
                self.model.disable_head()
            for images, labels in self.trainloader:
                outputs = self.model(images.to(self.device))
                labels = labels.to(self.device)
                loss = criterion(outputs, labels)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total += labels.size(0)
                correct += (torch.max(outputs.data, 1)[1] == labels).sum().item()

        # Save client state (head)
        if self.client_save_path is not None:
            torch.save(self.model.head.state_dict(), self.client_save_path)

        return {"loss": loss.item(), "accuracy": correct / total}

    def test(self) -> Dict[str, float]:
        """Test the model maintained in self.model.

        Returns
        -------
            Dict containing the test metrics.
        """
        # Load client state (head)
        if self.client_save_path is not None and os.path.isfile(self.client_save_path):
            self.model.head.load_state_dict(torch.load(self.client_save_path))

        num_finetune_epochs = DEFAULT_FINETUNE_EPOCHS
        if hasattr(self.config, "num_finetune_epochs"):
            num_finetune_epochs = int(self.config.num_finetune_epochs)

        if num_finetune_epochs > 0:
            optimizer = torch.optim.SGD(self.model.parameters(), lr=self.learning_rate)
            criterion = torch.nn.CrossEntropyLoss()
            self.model.train()
            for _ in range(num_finetune_epochs):
                for images, labels in self.trainloader:
                    outputs = self.model(images.to(self.device))
                    labels = labels.to(self.device)
                    loss = criterion(outputs, labels)
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()

        criterion = torch.nn.CrossEntropyLoss()
        correct, total, loss = 0, 0, 0.0

        self.model.eval()
        with torch.no_grad():
            for images, labels in self.testloader:
                outputs = self.model(images.to(self.device))
                labels = labels.to(self.device)
                loss += criterion(outputs, labels).item()
                total += labels.size(0)
                correct += (torch.max(outputs.data, 1)[1] == labels).sum().item()

        return {
            "loss": loss / len(self.testloader.dataset),
            "accuracy": correct / total,
        }

    def train_dataset_size(self) -> int:
        """Return train data set size."""
        return len(self.trainloader.dataset)

    def test_dataset_size(self) -> int:
        """Return test data set size."""
        return len(self.testloader.dataset)

    def total_dataset_size(self) -> int:
        """Return total data set size."""
        return len(self.trainloader.dataset) + len(self.testloader.dataset)