"""Matching: fuse recognisers, one-face-one-student assignment, uncertainty flags."""
import numpy as np
from scipy.optimize import linear_sum_assignment
from .. import config


def confidence_pct(d, t_reject=config.T_REJECT):
    """0-100 display score: distance 0.30 -> 100 %, t_reject -> 0 %."""
    return float(np.clip((t_reject - d) / (t_reject - 0.30), 0, 1) * 100)


def assign(D, t_reject):
    """Hungarian assignment (each student gets at most one face). D: F x S.
    Returns dict face_idx -> student_idx for pairs within t_reject."""
    if D.size == 0: return {}
    r, c = linear_sum_assignment(D)
    return {int(i): int(j) for i, j in zip(r, c) if D[i, j] <= t_reject}


def match_photo(Ds, cfg=None):
    """Ds: list of per-recogniser distance matrices (F x S). Returns per-face decisions."""
    cfg = cfg or {}
    t_acc = cfg.get("t_accept", config.T_ACCEPT)
    t_rej = cfg.get("t_reject", config.T_REJECT)
    margin_min = cfg.get("margin_min", config.MARGIN_MIN)
    use_assign = cfg.get("one_face_one_student", True)
    D = np.mean(Ds, axis=0)
    F, S = D.shape
    if use_assign:
        A = assign(D, t_rej)
    else:
        A = {i: int(np.argmin(D[i])) for i in range(F) if D[i].min() <= t_rej}
    per_model = [assign(Dm, t_rej) if use_assign else {i: int(np.argmin(Dm[i])) for i in range(F)} for Dm in Ds]
    out = []
    for i in range(F):
        j = A.get(i)
        rec = {"student_idx": j, "dist": None, "second": None, "flags": [], "argmin_idx": int(np.argmin(D[i])) if S else None}
        if j is not None:
            d = float(D[i, j]); rec["dist"] = d
            others = np.delete(D[i], j)
            rec["second"] = float(others.min()) if others.size else None
            if d > t_acc: rec["flags"].append("weak_match")
            if rec["second"] is not None and rec["second"] - d < margin_min: rec["flags"].append("close_call")
            if rec["argmin_idx"] != j: rec["flags"].append("resolved_by_assignment")
            if len(Ds) > 1 and any(pm.get(i) != j for pm in per_model): rec["flags"].append("models_disagree")
        else:
            rec["dist"] = float(D[i].min()) if S else None
            rec["flags"].append("unknown_face")
        out.append(rec)
    return out
