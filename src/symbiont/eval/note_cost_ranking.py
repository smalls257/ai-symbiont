"""How well a risk ranks trouble steps above calm ones, threshold-free (T46 "Is it the data?").

ROC AUC answers whether the features carry signal at all; precision among the riskiest steps
answers whether any threshold could reach a note's break-even. Pure numpy.
"""

import numpy as np

TOP_SHARES = (0.01, 0.05, 0.2)


def roc_auc(risks: np.ndarray, followed: np.ndarray) -> float:
    """Mann-Whitney AUC with ties counted as half; raises without both kinds of step."""
    labels = np.asarray(followed, dtype=bool)
    positives, negatives = int(labels.sum()), int((~labels).sum())
    if positives == 0 or negatives == 0:
        raise ValueError("AUC needs steps both followed and not followed by trouble")
    _, inverse, tie_counts = np.unique(risks, return_inverse=True, return_counts=True)
    upper = np.cumsum(tie_counts)
    midrank = (upper - (tie_counts - 1) / 2.0)[inverse]
    rank_sum = float(midrank[labels].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def top_share_precision(risks: np.ndarray, followed: np.ndarray, share: float) -> float:
    """Share of trouble among the riskiest `share` of steps (stable order breaks ties)."""
    n_top = max(1, int(round(share * len(risks))))
    order = np.argsort(-np.asarray(risks), kind="stable")[:n_top]
    return float(np.asarray(followed, dtype=bool)[order].mean())


def ranking(risks: np.ndarray, followed: np.ndarray) -> dict[str, float]:
    """AUC, base rate and precision among the top shares of steps."""
    return {
        "roc_auc": roc_auc(risks, followed),
        "base_rate": float(np.mean(followed)),
        **{
            f"precision_top_{share:g}": top_share_precision(risks, followed, share)
            for share in TOP_SHARES
        },
    }
