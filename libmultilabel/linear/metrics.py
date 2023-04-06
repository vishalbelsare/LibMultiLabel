from __future__ import annotations

import re

import numpy as np

__all__ = ['get_metrics',
           'compute_metrics',
           'tabulate_metrics',
           'MetricCollection']


class RPrecision:
    def __init__(self, top_k: int):
        self.top_k = top_k
        self.score = 0
        self.num_sample = 0

    def update(self, preds: np.ndarray, target: np.ndarray):
        assert preds.shape == target.shape  # (batch_size, num_classes)
        top_k_ind = np.argpartition(preds, -self.top_k)[:, -self.top_k:]
        num_relevant = np.take_along_axis(
            target, top_k_ind, axis=-1).sum(axis=-1)  # (batch_size, top_k)
        self.score += np.nan_to_num(
            num_relevant / np.minimum(self.top_k, target.sum(axis=-1)),
            posinf=0.
        ).sum()
        self.num_sample += preds.shape[0]

    def compute(self) -> float:
        return self.score / self.num_sample

    def reset(self):
        self.score = 0
        self.num_sample = 0


class Precision:
    def __init__(self, num_classes: int, average: str, top_k: int):
        if average != 'samples':
            raise ValueError('unsupported average')

        self.top_k = top_k
        self.score = 0
        self.num_sample = 0

    def update(self, preds: np.ndarray, target: np.ndarray):
        assert preds.shape == target.shape  # (batch_size, num_classes)
        top_k_ind = np.argpartition(preds, -self.top_k)[:, -self.top_k:]
        num_relevant = np.take_along_axis(target, top_k_ind, -1).sum()
        self.score += num_relevant / self.top_k
        self.num_sample += preds.shape[0]

    def compute(self) -> float:
        return self.score / self.num_sample

    def reset(self):
        self.score = 0
        self.num_sample = 0


class F1:
    def __init__(self, num_classes: int, metric_threshold: float, average: str, multiclass=False):
        self.num_classes = num_classes
        self.metric_threshold = metric_threshold
        if average not in {'macro', 'micro', 'another-macro'}:
            raise ValueError('unsupported average')
        self.average = average
        self.multiclass = multiclass
        self.tp = self.fp = self.fn = 0

    def update(self, preds: np.ndarray, target: np.ndarray):
        assert preds.shape == target.shape  # (batch_size, num_classes)
        if self.multiclass:
            max_idx = np.argmax(preds, axis=1).reshape(-1, 1)
            preds = np.zeros(preds.shape)
            np.put_along_axis(preds, max_idx, 1, axis=1)
        else:
            preds = preds > self.metric_threshold
        self.tp += np.logical_and(target == 1, preds == 1).sum(axis=0)
        self.fn += np.logical_and(target == 1, preds == 0).sum(axis=0)
        self.fp += np.logical_and(target == 0, preds == 1).sum(axis=0)

    def compute(self) -> float:
        prev_settings = np.seterr('ignore')

        if self.average == 'macro':
            score = np.nansum(
                2*self.tp / (2*self.tp + self.fp + self.fn)) / self.num_classes
        elif self.average == 'micro':
            score = np.nan_to_num(2*np.sum(self.tp) /
                                  np.sum(2*self.tp + self.fp + self.fn))
        elif self.average == 'another-macro':
            macro_prec = np.nansum(
                self.tp / (self.tp + self.fp)) / self.num_classes
            macro_recall = np.nansum(
                self.tp / (self.tp + self.fn)) / self.num_classes
            score = np.nan_to_num(
                2 * macro_prec * macro_recall / (macro_prec + macro_recall))

        np.seterr(**prev_settings)
        return score

    def reset(self):
        self.tp = self.fp = self.fn = 0


class MetricCollection(dict):
    """A collection of metrics created by get_metrics.
    MetricCollection computes metric values in two steps. First, batches of
    decision values and labels are added with update(). After all instances have been
    added, compute() computes the metric values from the accumulated batches.
    """
    def __init__(self, metrics):
        self.metrics = metrics

    def update(self, preds: np.ndarray, target: np.ndarray):
        """Adds a batch of decision values and labels.

        Args:
            preds (np.ndarray): A matrix of decision values with dimensions number of instances * number of classes.
            target (np.ndarray): A 0/1 matrix of labels with dimensions number of instances * number of classes.
        """
        assert preds.shape == target.shape  # (batch_size, num_classes)
        for metric in self.metrics.values():
            metric.update(preds, target)

    def compute(self) -> dict[str, float]:
        """Computes the metrics from the accumulated batches of decision values and labels.

        Returns:
            dict[str, float]: A dictionary of metric values.
        """
        ret = {}
        for name, metric in self.metrics.items():
            ret[name] = metric.compute()
        return ret

    def reset(self):
        """Clears the accumulated batches of decision values and labels.
        """
        for metric in self.metrics.values():
            metric.reset()


def get_metrics(metric_threshold: float,
                monitor_metrics: list[str],
                num_classes: int,
                multiclass: bool = False
                ) -> MetricCollection:
    """Get a collection of metrics by their names.
    See MetricCollection for more details.

    Args:
        metric_threshold (float): The decision value threshold over which a label is predicted as positive.
        monitor_metrics (list[str]): A list of metric names.
        num_classes (int): The number of classes.
        multiclass (bool, optional): Enable multiclass mode. Defaults to False.

    Returns:
        MetricCollection: A metric collection of the list of metrics.
    """
    if monitor_metrics is None:
        monitor_metrics = []
    metrics = {}
    for metric in monitor_metrics:
        if re.match('P@\d+', metric):
            metrics[metric] = Precision(
                num_classes, average='samples', top_k=int(metric[2:]))
        elif re.match('RP@\d+', metric):
            metrics[metric] = RPrecision(top_k=int(metric[3:]))
        elif metric in {'Another-Macro-F1', 'Macro-F1', 'Micro-F1'}:
            metrics[metric] = F1(num_classes, metric_threshold,
                                 average=metric[:-3].lower(),
                                 multiclass=multiclass)
        else:
            raise ValueError(f'invalid metric: {metric}')

    return MetricCollection(metrics)


def compute_metrics(preds: np.ndarray,
                    target: np.ndarray,
                    metric_threshold: float,
                    monitor_metrics: list[str],
                    multiclass: bool = False
                    ) -> dict[str, float]:
    """Compute metrics with decision values and labels.
    See get_metrics and MetricCollection if decision values and labels are too
    large to hold in memory.


    Args:
        preds (np.ndarray): A matrix of decision values with dimensions number of instances * number of classes.
        target (np.ndarray): A 0/1 matrix of labels with dimensions number of instances * number of classes.
        metric_threshold (float): The decision value threshold over which a label is predicted as positive.
        monitor_metrics (list[str]): A list of metric names.
        multiclass (bool, optional): Enable multiclass mode. Defaults to False.

    Returns:
        dict[str, float]: A dictionary of metric values.
    """
    assert preds.shape == target.shape

    metric = get_metrics(metric_threshold, monitor_metrics,
                         preds.shape[1], multiclass)
    metric.update(preds, target)
    return metric.compute()


def tabulate_metrics(metric_dict: dict[str, float], split: str) -> str:
    """Convert a dictionary of metric values into a pretty formatted string for printing.

    Args:
        metric_dict (dict[str, float]): A dictionary of metric values.
        split (str): Name of the data split.

    Returns:
        str: Pretty formatted string.
    """
    msg = f'====== {split} dataset evaluation result =======\n'
    header = '|'.join([f'{k:^18}' for k in metric_dict.keys()])
    values = '|'.join([f'{x * 100:^18.4f}' if isinstance(x, (np.floating,
                      float)) else f'{x:^18}' for x in metric_dict.values()])
    msg += f"|{header}|\n|{'-----------------:|' * len(metric_dict)}\n|{values}|\n"
    return msg
