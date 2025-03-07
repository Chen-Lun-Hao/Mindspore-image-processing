'''MobileNetV2'''
# coding:utf8
# pylint: disable=E0401
import mindspore
import mindspore.nn as nn
import mindspore.common.initializer as init


def _make_divisible(ch, divisor=8, min_ch=None):
    """
    This function is taken from the original tf repo.
    It ensures that all layers have a channel number that is divisible by 8
    It can be seen here:
    https://github.com/tensorflow/models/blob/master/research/slim/nets/mobilenet/mobilenet.py
    """
    if min_ch is None:
        min_ch = divisor
    new_ch = max(min_ch, int(ch + divisor / 2) // divisor * divisor)
    # Make sure that round down does not go down by more than 10%.
    if new_ch < 0.9 * ch:
        new_ch += divisor
    return new_ch


class ConvBNReLU(nn.SequentialCell):
    '''ConvBNReLU'''

    def __init__(self, in_channel, out_channel, kernel_size=3, stride=1, groups=1):
        padding = (kernel_size - 1) // 2
        super().__init__(
            nn.Conv2d(in_channel, out_channel, kernel_size,
                      stride, padding=padding, group=groups, has_bias=False),
            nn.BatchNorm2d(out_channel),
            nn.ReLU6()
        )


class InvertedResidual(nn.Cell):
    '''InvertedResidual'''

    def __init__(self, in_channel, out_channel, stride, expand_ratio):
        super().__init__()
        hidden_channel = in_channel * expand_ratio
        self.use_shortcut = stride == 1 and in_channel == out_channel

        layers = []
        if expand_ratio != 1:
            # 1x1 pointwise conv
            layers.append(ConvBNReLU(
                in_channel, hidden_channel, kernel_size=1))
        layers.extend([
            # 3x3 depthwise conv
            ConvBNReLU(hidden_channel, hidden_channel,
                       stride=stride, groups=hidden_channel),
            # 1x1 pointwise conv(linear)
            nn.Conv2d(hidden_channel, out_channel,
                      kernel_size=1, has_bias=False),
            nn.BatchNorm2d(out_channel),
        ])

        self.conv = nn.SequentialCell(*layers)

    def construct(self, x):
        if self.use_shortcut:
            out = x + self.conv(x)
        else:
            out = self.conv(x)
        return out


class MobileNetV2(nn.Cell):
    '''MobileNetV2'''

    def __init__(self, num_classes=1000, alpha=1.0, round_nearest=8):
        super().__init__()
        block = InvertedResidual
        input_channel = _make_divisible(32 * alpha, round_nearest)
        last_channel = _make_divisible(1280 * alpha, round_nearest)

        inverted_residual_setting = [
            # t, c, n, s
            [1, 16, 1, 1],
            [6, 24, 2, 2],
            [6, 32, 3, 2],
            [6, 64, 4, 2],
            [6, 96, 3, 1],
            [6, 160, 3, 2],
            [6, 320, 1, 1],
        ]

        features = []
        # conv1 layer
        features.append(ConvBNReLU(3, input_channel, stride=2))
        # building inverted residual residual blockes
        for t, c, n, s in inverted_residual_setting:
            output_channel = _make_divisible(c * alpha, round_nearest)
            for i in range(n):
                stride = s if i == 0 else 1
                features.append(
                    block(input_channel, output_channel, stride, expand_ratio=t))
                input_channel = output_channel
        # building last several layers
        features.append(ConvBNReLU(input_channel, last_channel, 1))
        # combine feature layers
        self.features = nn.SequentialCell(*features)

        # building classifier
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.classifier = nn.SequentialCell(
            nn.Dropout(0.2),
            nn.Dense(last_channel, num_classes)
        )

        # weight initialization
        for _, cell in self.cells_and_names():
            if isinstance(cell, nn.Conv2d):
                cell.weight.set_data(init.initializer(
                    init.HeUniform(), cell.weight.shape, cell.weight.dtype))
                if cell.bias is not None:
                    cell.bias.set_data(init.initializer(
                        "zeros", cell.bias.shape, cell.bias.dtype))
            elif isinstance(cell, nn.BatchNorm2d):
                cell.weight.set_data(init.initializer(
                    "ones", cell.weight.shape, cell.weight.dtype))
                cell.bias.set_data(init.initializer(
                    "zeros", cell.bias.shape, cell.bias.dtype))
            elif isinstance(cell, nn.Dense):
                cell.weight.set_data(
                    init.initializer(init.TruncatedNormal(
                        sigma=0.01), cell.weight.shape, cell.weight.dtype)
                )
                if cell.bias is not None:
                    cell.bias.set_data(init.initializer(
                        "zeros", cell.bias.shape, cell.bias.dtype))

    def construct(self, x):
        x = self.features(x)
        x = self.avgpool(x)
        x = mindspore.ops.flatten(x, start_dim=1)
        x = self.classifier(x)
        return x
