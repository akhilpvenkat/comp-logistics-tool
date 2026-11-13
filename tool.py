import sys
import numpy as np
from scipy.optimize import linprog
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from stage1_scorer import load_data


def lp_upper_bound(D):
    S, P, Dd, M, K = D["suppliers"], D["procs"], D["dists"], D["mats"], D["prods"]
    idx, cost, ub = {}, [], []

    def add(key, c, u):
        idx[key] = len(cost)
        cost.append(c)
        ub.append(u)

    for s in S:
        for p in P:
            for m in M:
                add(("ms", s, p, m), D["s_cost"][(s, m)] + D["mat_ship"][m] * D["dist"][(s, p)], D["s_max"][(s, m)])
    for p in P:
        for k in K:
            add(("mk", p, k), D["p_time"][(p, k)] * D["p_rate"][p], D["p_cap"][p] / D["p_time"][(p, k)])
    for p in P:
        for d in Dd:
            for k in K:
                add(("sd", p, d, k), D["mat_ship"][k] * D["dist"][(p, d)] - D["d_price"][(d, k)], D["d_demand"][(d, k)])

    A, b = [], []

    def le(coefs, rhs):
        row = np.zeros(len(cost))
        for key, v in coefs:
            row[idx[key]] = v
        A.append(row)
        b.append(rhs)

    for s in S:
        for m in M:
            le([(("ms", s, p, m), 1) for p in P], D["s_max"][(s, m)])
    for p in P:
        for m in M:
            le([(("ms", s, p, m), -1) for s in S] + [(("mk", p, k), D["req"][(k, m)]) for k in K], 0)
        le([(("mk", p, k), D["p_time"][(p, k)]) for k in K], D["p_cap"][p])
        for k in K:
            le([(("sd", p, d, k), 1) for d in Dd] + [(("mk", p, k), -1)], 0)
    for d in Dd:
        for k in K:
            le([(("sd", p, d, k), 1) for p in P], D["d_demand"][(d, k)])

    res = linprog(cost, A_ub=np.array(A), b_ub=np.array(b), bounds=list(zip([0] * len(cost), ub)), method="highs")
    return -res.fun


if __name__ == "__main__":
    data = load_data(sys.argv[1])
    print(f"LP relaxation upper bound = ${lp_upper_bound(data):,.2f}")
