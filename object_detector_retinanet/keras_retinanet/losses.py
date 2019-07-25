"""
Copyright 2017-2018 Fizyr (https://fizyr.com)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import keras
from . import backend


def focal(alpha=0.25, gamma=2.0):
    """ Create a functor for computing the focal loss.

    Args
        alpha: Scale the focal weight with alpha.
        gamma: Take the power of the focal weight with gamma.

    Returns
        A functor that computes the focal loss using the alpha and gamma.
    """

    def _focal(y_true, y_pred):
        """ Compute the focal loss given the target tensor and the predicted tensor.

        As defined in https://arxiv.org/abs/1708.02002

        Args
            y_true: Tensor of target data from the generator with shape (B, N, num_classes).
            y_pred: Tensor of predicted data from the network with shape (B, N, num_classes).

        Returns
            The focal loss of y_pred w.r.t. y_true.
        """
        labels = y_true
        classification = y_pred

        # filter out "ignore" anchors
        anchor_state = keras.backend.max(labels, axis=2)  # -1 for ignore, 0 for background, 1 for object
        indices = backend.where(keras.backend.not_equal(anchor_state, -1))
        labels = backend.gather_nd(labels, indices)
        classification = backend.gather_nd(classification, indices)

        # compute the focal loss
        alpha_factor = keras.backend.ones_like(labels) * alpha
        alpha_factor = backend.where(keras.backend.equal(labels, 1), alpha_factor, 1 - alpha_factor)
        focal_weight = backend.where(keras.backend.equal(labels, 1), 1 - classification, classification)
        focal_weight = alpha_factor * focal_weight ** gamma

        cls_loss = focal_weight * keras.backend.binary_crossentropy(labels, classification)

        # compute the normalizer: the number of positive anchors
        normalizer = backend.where(keras.backend.equal(anchor_state, 1))
        normalizer = keras.backend.cast(keras.backend.shape(normalizer)[0], keras.backend.floatx())
        normalizer = keras.backend.maximum(1.0, normalizer)

        return keras.backend.sum(cls_loss) / normalizer

    return _focal


def smooth_l1(sigma=3.0):
    """ Create a smooth L1 loss functor.

    Args
        sigma: This argument defines the point where the loss changes from L2 to L1.

    Returns
        A functor for computing the smooth L1 loss given target data and predicted data.
    """
    sigma_squared = sigma ** 2

    def _smooth_l1(y_true, y_pred):
        """ Compute the smooth L1 loss of y_pred w.r.t. y_true.

        Args
            y_true: Tensor from the generator of shape (B, N, 5). The last value for each box is the state of the anchor (ignore, negative, positive).
            y_pred: Tensor from the network of shape (B, N, 4).

        Returns
            The smooth L1 loss of y_pred w.r.t. y_true.
        """
        # separate target and state
        regression = y_pred
        regression_target = y_true[:, :, :4]
        anchor_state = y_true[:, :, 4]

        # filter out "ignore" anchors
        indices = backend.where(keras.backend.equal(anchor_state, 1))
        regression = backend.gather_nd(regression, indices)
        regression_target = backend.gather_nd(regression_target, indices)

        # compute smooth L1 loss
        # f(x) = 0.5 * (sigma * x)^2          if |x| < 1 / sigma / sigma
        #        |x| - 0.5 / sigma / sigma    otherwise
        regression_diff = regression - regression_target
        regression_diff = keras.backend.abs(regression_diff)
        regression_loss = backend.where(
            keras.backend.less(regression_diff, 1.0 / sigma_squared),
            0.5 * sigma_squared * keras.backend.pow(regression_diff, 2),
            regression_diff - 0.5 / sigma_squared
        )

        # compute the normalizer: the number of positive anchors
        normalizer = keras.backend.maximum(1, keras.backend.shape(indices)[0])
        normalizer = keras.backend.cast(normalizer, dtype=keras.backend.floatx())
        return keras.backend.sum(regression_loss) / normalizer

    return _smooth_l1


def iou_score():
    def iou_loss(y_true, y_pred):
        # separate target and state
        regression = y_pred[:, :, :4]
        y_pred_iou = y_pred[:, :, 4]
        y_pred_hard_scores = y_pred[:, :, 5]
        regression_target = y_true[:, :, :4]
        anchor_state = y_true[:, :, 4]

        # filter out "ignore" anchors
        indices = backend.where((keras.backend.equal(anchor_state, 1) & (keras.backend.greater(y_pred_hard_scores, 0.1))))
        regression = backend.gather_nd(regression, indices)
        y_pred_iou = backend.gather_nd(y_pred_iou, indices)
        y_pred_iou = keras.backend.expand_dims(y_pred_iou)

        regression_target = backend.gather_nd(regression_target, indices)

        y_true_iou = intersection_over_union(regression_target, regression)
        iou_loss = keras.backend.binary_crossentropy(output=y_pred_iou, target=y_true_iou)

        # compute the normalizer: the number of positive anchors
        normalizer = keras.backend.maximum(1, keras.backend.shape(indices)[0])
        normalizer = keras.backend.cast(normalizer, dtype=keras.backend.floatx())
        return keras.backend.sum(iou_loss) / normalizer

    return iou_loss


def intersection_over_union(y_true_masks, y_pred_masks):
    w_true = y_true_masks[:, 2::4] - y_true_masks[:, 0::4]
    h_true = y_true_masks[:, 3::4] - y_true_masks[:, 1::4]
    gt_area = w_true * h_true

    w_pred = y_pred_masks[:, 2::4] - y_pred_masks[:, 0::4]
    h_pred = y_pred_masks[:, 3::4] - y_pred_masks[:, 1::4]
    pred_area = w_pred * h_pred
    w_intersection = keras.backend.maximum(0., keras.backend.minimum(y_true_masks[:, 2::4],
                                                                     y_pred_masks[:, 2::4]) - keras.backend.maximum(
        y_true_masks[:, 0::4], y_pred_masks[:, 0::4]))
    h_intersection = keras.backend.maximum(0., keras.backend.minimum(y_true_masks[:, 3::4],
                                                                     y_pred_masks[:, 3::4]) - keras.backend.maximum(
        y_true_masks[:, 1::4], y_pred_masks[:, 1::4]))
    intersection_area = w_intersection * h_intersection

    union = pred_area + gt_area - intersection_area + keras.backend.epsilon()
    return intersection_area / union
