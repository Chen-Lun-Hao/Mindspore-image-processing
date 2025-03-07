'''eval'''
# pylint:disable=E0401,R0201
import copy
import numpy as np

from pycocotools.cocoeval import COCOeval
from pycocotools.coco import COCO
import pycocotools.mask as mask_util


class EvalCOCOMetric:
    '''EvalCOCOMetric'''

    def __init__(self,
                 coco: COCO = None,
                 iou_type: str = None,
                 results_file_name: str = "predict_results.json",
                 classes_mapping: dict = None):
        self.coco = copy.deepcopy(coco)
        self.img_ids = []  # 记录每个进程处理图片的ids
        self.results = []
        self.aggregation_results = None
        self.classes_mapping = classes_mapping
        self.coco_evaluator = None
        assert iou_type in ["bbox", "segm", "keypoints"]
        self.iou_type = iou_type
        self.results_file_name = results_file_name

    def prepare_for_coco_detection(self, targets, outputs):
        """将预测的结果转换成COCOeval指定的格式，针对目标检测任务"""
        # 遍历每张图像的预测结果
        for target, output in zip(targets, outputs):
            if len(output) == 0:
                continue

            img_id = int(target["image_id"])
            if img_id in self.img_ids:
                # 防止出现重复的数据
                continue
            self.img_ids.append(img_id)
            per_image_boxes = output["boxes"]
            # 对于coco_eval, 需要的每个box的数据格式为[x_min, y_min, w, h]
            # 而我们预测的box格式是[x_min, y_min, x_max, y_max]，所以需要转下格式
            per_image_boxes[:, 2:] -= per_image_boxes[:, :2]
            per_image_classes = output["labels"].tolist()
            per_image_scores = output["scores"].tolist()

            res_list = []
            # 遍历每个目标的信息
            for object_score, object_class, object_box in zip(
                    per_image_scores, per_image_classes, per_image_boxes):
                object_score = float(object_score)
                class_idx = int(object_class)
                if self.classes_mapping is not None:
                    class_idx = int(self.classes_mapping[str(class_idx)])
                # We recommend rounding coordinates to the nearest tenth of a pixel
                # to reduce resulting JSON file size.
                object_box = [round(b, 2) for b in object_box.tolist()]

                res = {"image_id": img_id,
                       "category_id": class_idx,
                       "bbox": object_box,
                       "score": round(object_score, 3)}
                res_list.append(res)
            self.results.append(res_list)

    def prepare_for_coco_segmentation(self, targets, outputs):
        """将预测的结果转换成COCOeval指定的格式，针对实例分割任务"""
        # 遍历每张图像的预测结果
        for target, output in zip(targets, outputs):
            if len(output) == 0:
                continue

            img_id = int(target["image_id"])
            if img_id in self.img_ids:
                # 防止出现重复的数据
                continue

            self.img_ids.append(img_id)
            per_image_masks = output["masks"]
            per_image_classes = output["labels"].tolist()
            per_image_scores = output["scores"].tolist()

            masks = per_image_masks > 0.5

            res_list = []
            # 遍历每个目标的信息
            for mask, label, score in zip(masks, per_image_classes, per_image_scores):
                rle = mask_util.encode(
                    np.array(mask[0, :, :, np.newaxis], dtype=np.uint8, order="F"))[0]
                rle["counts"] = rle["counts"].decode("utf-8")

                class_idx = int(label)
                if self.classes_mapping is not None:
                    class_idx = int(self.classes_mapping[str(class_idx)])

                res = {"image_id": img_id,
                       "category_id": class_idx,
                       "segmentation": rle,
                       "score": round(score, 3)}
                res_list.append(res)
            self.results.append(res_list)

    def update(self, targets, outputs):
        '''update'''
        if self.iou_type == "bbox":
            self.prepare_for_coco_detection(targets, outputs)
        elif self.iou_type == "segm":
            self.prepare_for_coco_segmentation(targets, outputs)
        else:
            raise KeyError(f"not support iou_type: {self.iou_type}")

    def evaluate(self):
        '''evaluate'''
        # accumulate predictions from all images
        coco_true = self.coco
        coco_pre = coco_true.loadRes(self.results_file_name)

        self.coco_evaluator = COCOeval(
            cocoGt=coco_true, cocoDt=coco_pre, iouType=self.iou_type)

        self.coco_evaluator.evaluate()
        self.coco_evaluator.accumulate()
        print(f"IoU metric: {self.iou_type}")
        self.coco_evaluator.summarize()

        coco_info = self.coco_evaluator.stats.tolist()  # numpy to list
        return coco_info
