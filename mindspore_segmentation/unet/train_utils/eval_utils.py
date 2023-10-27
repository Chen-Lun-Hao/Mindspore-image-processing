'''utils'''
import mindspore as ms
from mindspore import ops, Tensor

from .dice_coefficient_loss import multiclass_dice_coeff, build_target


class ConfusionMatrix():
    '''ConfusionMatrix'''

    def __init__(self, num_classes):
        self.num_classes = num_classes
        self.mat = None

    def update(self, a, b):
        '''update'''
        n = self.num_classes
        if self.mat is None:
            # 创建混淆矩阵
            self.mat = ops.zeros((n, n), dtype=ms.int64)
        # 寻找GT中为目标的像素索引
        k = (a >= 0) & (a < n)
        # 统计像素真实类别a[k]被预测成类别b[k]的个数(这里的做法很巧妙)
        inds = n * a[k].to(ms.int64) + b[k]
        self.mat += ops.bincount(inds, minlength=n**2).reshape(n, n)

    def reset(self):
        '''reset'''
        if self.mat is not None:
            self.mat.zero_()

    def compute(self):
        '''compute'''
        h = self.mat.float()
        # 计算全局预测准确率(混淆矩阵的对角线为预测正确的个数)
        acc_global = ops.diag(h).sum() / h.sum()
        # 计算每个类别的准确率
        acc = ops.diag(h) / h.sum(1)
        # 计算每个类别预测与真实目标的iou
        iu = ops.diag(h) / (h.sum(1) + h.sum(0) - ops.diag(h))
        return acc_global, acc, iu

    def __str__(self):
        acc_global, acc, iu = self.compute()
        return (
            'global correct: {:.1f}\n'
            'average row correct: {}\n'
            'IoU: {}\n'
            'mean IoU: {:.1f}').format(
                acc_global.item() * 100,
                ['{:.1f}'.format(i) for i in (acc * 100).tolist()],
                ['{:.1f}'.format(i) for i in (iu * 100).tolist()],
                iu.mean().item() * 100)


class DiceCoefficient():
    '''DiceCoefficient'''

    def __init__(self, num_classes: int = 2, ignore_index: int = -100):
        self.cumulative_dice = None
        self.num_classes = num_classes
        self.ignore_index = ignore_index
        self.count = None

    def update(self, pred, target):
        '''update'''
        if self.cumulative_dice is None:
            self.cumulative_dice = ops.zeros(
                1, dtype=pred.dtype)
        on_value, off_value = Tensor(
            1.0, ms.float32), Tensor(0.0, ms.float32)
        if self.count is None:
            self.count = ops.zeros(1, dtype=pred.dtype)
        # compute the Dice score, ignoring background
        pred = ops.one_hot(pred.argmax(dim=1), self.num_classes, on_value, off_value).permute(
            0, 3, 1, 2).float()
        dice_target = build_target(target, self.num_classes, self.ignore_index)
        self.cumulative_dice += multiclass_dice_coeff(
            pred[:, 1:], dice_target[:, 1:], ignore_index=self.ignore_index)
        self.count += 1

    @property
    def value(self):
        '''value'''
        if self.count == 0:
            out = 0
        else:
            out = self.cumulative_dice / self.count
        return out

    def reset(self):
        '''teset'''
        if self.cumulative_dice is not None:
            self.cumulative_dice.zero_()

        if self.count is not None:
            self.count.zeros_()
