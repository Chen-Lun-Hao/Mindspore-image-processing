"""
model
"""

import math
from collections import OrderedDict
from typing import Tuple

import mindspore.common.initializer as init
from mindspore import Tensor, nn, ops


class GlobalAvgPooling(nn.Cell):
    """
    GlobalAvgPooling, same as torch.nn.AdaptiveAvgPool2d when output shape is 1
    """

    def __init__(self, keep_dims: bool = False) -> None:
        super().__init__()
        self.keep_dims = keep_dims

    def construct(self, x):
        x = ops.mean(x, axis=(2, 3), keep_dims=self.keep_dims)
        return x


class _DenseLayer(nn.Cell):
    """Basic unit of DenseBlock (using bottleneck layer)"""

    def __init__(
        self,
        num_input_features: int,
        growth_rate: int,
        bn_size: int,
        drop_rate: float,
    ) -> None:
        super().__init__()
        self.norm1 = nn.BatchNorm2d(num_input_features)
        self.relu1 = nn.ReLU()
        self.conv1 = nn.Conv2d(
            num_input_features, bn_size * growth_rate, kernel_size=1, stride=1)

        self.norm2 = nn.BatchNorm2d(bn_size * growth_rate)
        self.relu2 = nn.ReLU()
        self.conv2 = nn.Conv2d(bn_size * growth_rate, growth_rate,
                               kernel_size=3, stride=1, pad_mode="pad", padding=1)

        self.drop_rate = drop_rate
        self.dropout = nn.Dropout(p=self.drop_rate)

    def construct(self, features: Tensor) -> Tensor:
        bottleneck = self.conv1(self.relu1(self.norm1(features)))
        new_features = self.conv2(self.relu2(self.norm2(bottleneck)))
        if self.drop_rate > 0.0:
            new_features = self.dropout(new_features)
        return new_features


class _DenseBlock(nn.Cell):
    """DenseBlock. Layers within a block are densely connected."""

    def __init__(
        self,
        num_layers: int,
        num_input_features: int,
        bn_size: int,
        growth_rate: int,
        drop_rate: float,
    ) -> None:
        super().__init__()
        self.cell_list = nn.CellList()
        for i in range(num_layers):
            layer = _DenseLayer(
                num_input_features=num_input_features + i * growth_rate,
                growth_rate=growth_rate,
                bn_size=bn_size,
                drop_rate=drop_rate,
            )
            self.cell_list.append(layer)

    def construct(self, init_features: Tensor) -> Tensor:
        features = init_features
        for layer in self.cell_list:
            new_features = layer(features)
            features = ops.concat((features, new_features), axis=1)
        return features


class _Transition(nn.Cell):
    """Transition layer between two adjacent DenseBlock"""

    def __init__(
        self,
        num_input_features: int,
        num_output_features: int,
    ) -> None:
        super().__init__()
        self.features = nn.SequentialCell(OrderedDict([
            ("norm", nn.BatchNorm2d(num_input_features)),
            ("relu", nn.ReLU()),
            ("conv", nn.Conv2d(num_input_features,
             num_output_features, kernel_size=1, stride=1)),
            ("pool", nn.AvgPool2d(kernel_size=2, stride=2))
        ]))

    def construct(self, x: Tensor) -> Tensor:
        x = self.features(x)
        return x


class DenseNet(nn.Cell):
    r"""Densenet-BC model class, based on
    `"Densely Connected Convolutional Networks" <https://arxiv.org/pdf/1608.06993.pdf>`_

    Args:
        growth_rate: how many filters to add each layer (`k` in paper). Default: 32.
        block_config: how many layers in each pooling block. Default: (6, 12, 24, 16).
        num_init_features: number of filters in the first Conv2d. Default: 64.
        bn_size (int): multiplicative factor for number of bottleneck layers
          (i.e. bn_size * k features in the bottleneck layer). Default: 4.
        drop_rate: dropout rate after each dense layer. Default: 0.
        in_channels: number of input channels. Default: 3.
        num_classes: number of classification classes. Default: 1000.
    """

    def __init__(
        self,
        growth_rate: int = 32,
        block_config: Tuple[int, int, int, int] = (6, 12, 24, 16),
        num_init_features: int = 64,
        bn_size: int = 4,
        drop_rate: float = 0.0,
        in_channels: int = 3,
        num_classes: int = 1000,
    ) -> None:
        super().__init__()
        layers = OrderedDict()
        # first Conv2d
        num_features = num_init_features
        layers["conv0"] = nn.Conv2d(
            in_channels, num_features, kernel_size=7, stride=2, pad_mode="pad", padding=3)
        layers["norm0"] = nn.BatchNorm2d(num_features)
        layers["relu0"] = nn.ReLU()
        layers["pool0"] = nn.SequentialCell([
            nn.Pad(paddings=((0, 0), (0, 0), (1, 1), (1, 1)), mode="CONSTANT"),
            nn.MaxPool2d(kernel_size=3, stride=2),
        ])

        # DenseBlock
        for i, num_layers in enumerate(block_config):
            block = _DenseBlock(
                num_layers=num_layers,
                num_input_features=num_features,
                bn_size=bn_size,
                growth_rate=growth_rate,
                drop_rate=drop_rate,
            )
            layers[f"denseblock{i + 1}"] = block
            num_features += num_layers * growth_rate
            if i != len(block_config) - 1:
                transition = _Transition(num_features, num_features // 2)
                layers[f"transition{i + 1}"] = transition
                num_features = num_features // 2

        # final bn+ReLU
        layers["norm5"] = nn.BatchNorm2d(num_features)
        layers["relu5"] = nn.ReLU()

        self.num_features = num_features
        self.features = nn.SequentialCell(layers)
        self.pool = GlobalAvgPooling()
        self.classifier = nn.Dense(self.num_features, num_classes)
        self._initialize_weights()

    def _initialize_weights(self) -> None:
        """Initialize weights for cells."""
        for _, cell in self.cells_and_names():
            if isinstance(cell, nn.Conv2d):
                cell.weight.set_data(
                    init.initializer(init.HeNormal(math.sqrt(5), mode="fan_out", nonlinearity="relu"),
                                     cell.weight.shape, cell.weight.dtype))
                if cell.bias is not None:
                    cell.bias.set_data(
                        init.initializer(init.HeUniform(math.sqrt(5), mode="fan_in", nonlinearity="leaky_relu"),
                                         cell.bias.shape, cell.bias.dtype))
            elif isinstance(cell, nn.BatchNorm2d):
                cell.gamma.set_data(init.initializer(
                    "ones", cell.gamma.shape, cell.gamma.dtype))
                cell.beta.set_data(init.initializer(
                    "zeros", cell.beta.shape, cell.beta.dtype))
            elif isinstance(cell, nn.Dense):
                cell.weight.set_data(
                    init.initializer(init.HeUniform(math.sqrt(5), mode="fan_in", nonlinearity="leaky_relu"),
                                     cell.weight.shape, cell.weight.dtype))
                if cell.bias is not None:
                    cell.bias.set_data(init.initializer(
                        "zeros", cell.bias.shape, cell.bias.dtype))

    def forward_features(self, x: Tensor) -> Tensor:
        '''features'''
        x = self.features(x)
        return x

    def forward_head(self, x: Tensor) -> Tensor:
        '''head'''
        x = self.pool(x)
        x = self.classifier(x)
        return x

    def construct(self, x: Tensor) -> Tensor:
        x = self.forward_features(x)
        x = self.forward_head(x)
        return x


def densenet121(num_classes: int = 1000, in_channels=3,
                growth_rate=32, block_config=(6, 12, 24, 16),
                num_init_features=64, bn_size=4, drop_rate=0.0) -> DenseNet:
    """Get 121 layers DenseNet model.
     Refer to the base class `models.DenseNet` for more details."""
    model = DenseNet(growth_rate=growth_rate, block_config=block_config,
                     num_init_features=num_init_features, in_channels=in_channels,
                     num_classes=num_classes, bn_size=bn_size, drop_rate=drop_rate)

    return model


def densenet161(num_classes: int = 1000, in_channels=3,
                growth_rate=48, block_config=(6, 12, 36, 24),
                num_init_features=96, bn_size=4, drop_rate=0.0) -> DenseNet:
    """Get 161 layers DenseNet model.
     Refer to the base class `models.DenseNet` for more details."""
    model = DenseNet(growth_rate=growth_rate, block_config=block_config,
                     num_init_features=num_init_features, in_channels=in_channels,
                     num_classes=num_classes, bn_size=bn_size, drop_rate=drop_rate)

    return model


def densenet169(num_classes: int = 1000, in_channels=3,
                growth_rate=32, block_config=(6, 12, 32, 32),
                num_init_features=64, bn_size=4, drop_rate=0.0) -> DenseNet:
    """Get 169 layers DenseNet model.
     Refer to the base class `models.DenseNet` for more details."""
    model = DenseNet(growth_rate=growth_rate, block_config=block_config,
                     num_init_features=num_init_features, in_channels=in_channels,
                     num_classes=num_classes, bn_size=bn_size, drop_rate=drop_rate)

    return model


def densenet201(num_classes: int = 1000, in_channels=3,
                growth_rate=32, block_config=(6, 12, 48, 32),
                num_init_features=64, bn_size=4, drop_rate=0.0) -> DenseNet:
    """Get 201 layers DenseNet model.
     Refer to the base class `models.DenseNet` for more details."""
    model = DenseNet(growth_rate=growth_rate, block_config=block_config,
                     num_init_features=num_init_features, in_channels=in_channels,
                     num_classes=num_classes, bn_size=bn_size, drop_rate=drop_rate)

    return model
