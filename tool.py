import sys, glob, os
import numpy as np
import pandas as pd
import openpyxl
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix

def _find(data_dir, key):
    key = key.replace(" ", "").replace("_", "").lower()
    for f in glob.glob(os.path.join(data_dir, "*.xlsx")):
        name = os.path.basename(f).replace(" ", "").replace("_", "").lower()
        if key in name:
            return f
    raise FileNotFoundError(f"no file matching '{key}' in {data_dir}")

def _code(label):
    return label.split("(")[-1].strip(") ")

def load_data(data_dir):
    sup = pd.read_excel(_find(data_dir, "suppliers"))
    proc = pd.read_excel(_find(data_dir, "processors"))
    dist = pd.read_excel(_find(data_dir, "distributors"))
    dmat = pd.read_excel(_find(data_dir, "distances"), index_col=0)
    req = pd.read_excel(_find(data_dir, "materialrequirements"), index_col=0)
    ship = pd.read_excel(_find(data_dir, "shippingcosts"), index_col=0)

    D = {}
    D["mats"] = [_code(c) for c in req.columns]
    D["prods"] = [_code(i) for i in req.index]
    D["mat_label"] = dict(zip(D["mats"], req.columns))
    D["prod_label"] = dict(zip(D["prods"], req.index))
    D["req"] = {(_code(p), _code(m)): float(req.loc[p, m]) for p in req.index for m in req.columns}
    D["mat_ship"] = {_code(i): float(ship.loc[i].iloc[-1]) for i in ship.index}

    D["suppliers"] = [c[c.index("(") + 1:-1] for c in sup.columns if c.startswith("Cost (")]
    D["s_cost"], D["s_max"] = {}, {}
    for _, row in sup.iterrows():
        m = _code(row.iloc[0])
        for s in D["suppliers"]:
            D["s_cost"][(s, m)] = float(row[f"Cost ({s})"])
            D["s_max"][(s, m)] = float(row[f"Max Monthly ({s})"])

    D["procs"] = list(proc.iloc[:, 0])
    D["p_rate"], D["p_cap"], D["p_time"] = {}, {}, {}
    for _, row in proc.iterrows():
        p = row.iloc[0]
        D["p_rate"][p] = float(row["Cost per Hour"])
        D["p_cap"][p] = float(row[[c for c in proc.columns if c.startswith("Max Capacity")][0]])
        for k in D["prods"]:
            col = [c for c in proc.columns if c.startswith("Processing Time") and f"({k})" in c][0]
            D["p_time"][(p, k)] = float(row[col])

    D["dists"] = list(dist.iloc[:, 0])
    D["d_demand"], D["d_price"] = {}, {}
    for _, row in dist.iterrows():
        d = row.iloc[0]
        for k in D["prods"]:
            D["d_demand"][(d, k)] = float(row[[c for c in dist.columns if c.startswith("Max Market Demand") and f"({k})" in c][0]])
            D["d_price"][(d, k)] = float(row[[c for c in dist.columns if c.startswith("Selling Price") and f"({k})" in c][0]])

    D["dist"] = {(a, b): float(dmat.loc[a, b]) for a in dmat.index for b in dmat.columns
                 if not np.isnan(dmat.loc[a, b])}
    return D

def score(D, sol):
    bad = []
    profit = 0.0
    for (s, m), q in sol["supply"].items():
        profit -= q * D["s_cost"][(s, m)]
        if q > D["s_max"][(s, m)] + 1e-9:
            bad.append(f"supply {s}/{m} {q} > max {D['s_max'][(s, m)]}")
    for (s, p, m), q in sol["ship_sp"].items():
        profit -= q * D["mat_ship"][m] * D["dist"][(s, p)]
    for s in D["suppliers"]:
        for m in D["mats"]:
            out = sum(sol["ship_sp"].get((s, p, m), 0) for p in D["procs"])
            if out > sol["supply"].get((s, m), 0) + 1e-6:
                bad.append(f"{s} ships more {m} than it buys")
    for p in D["procs"]:
        hrs = sum(sol["make"].get((p, k), 0) * D["p_time"][(p, k)] for k in D["prods"])
        profit -= hrs * D["p_rate"][p]
        if hrs > D["p_cap"][p] + 1e-9:
            bad.append(f"{p} hours {hrs:.2f} > cap {D['p_cap'][p]}")
        for m in D["mats"]:
            have = sum(sol["ship_sp"].get((s, p, m), 0) for s in D["suppliers"])
            need = sum(sol["make"].get((p, k), 0) * D["req"][(k, m)] for k in D["prods"])
            if need > have + 1e-6:
                bad.append(f"{p} needs {need:.1f} {m}, has {have:.1f}")
        for k in D["prods"]:
            out = sum(sol["send"].get((p, d, k), 0) for d in D["dists"])
            if out > sol["make"].get((p, k), 0) + 1e-9:
                bad.append(f"{p} ships more {k} than it makes")
    for (p, d, k), q in sol["send"].items():
        profit -= q * D["mat_ship"][k] * D["dist"][(p, d)]
    for d in D["dists"]:
        for k in D["prods"]:
            got = sum(sol["send"].get((p, d, k), 0) for p in D["procs"])
            sold = min(got, D["d_demand"][(d, k)])
            profit += sold * D["d_price"][(d, k)]
    return profit, bad

def optimize(D, time_limit=60):
    S, P, Dd, M, K = D["suppliers"], D["procs"], D["dists"], D["mats"], D["prods"]
    idx, names, cost, ub, integ = {}, [], [], [], []

    def add(key, c, u, scale=1.0):
        idx[key] = len(names)
        names.append(key)
        cost.append(c)
        ub.append(u)
        integ.append(1)

    for s in S:
        for p in P:
            for m in M:
                unit = D["s_cost"][(s, m)] + D["mat_ship"][m] * D["dist"][(s, p)]
                add(("ms", s, p, m), 0.1 * unit, D["s_max"][(s, m)] * 10)
    for p in P:
        for k in K:
            add(("mk", p, k), D["p_time"][(p, k)] * D["p_rate"][p], np.floor(D["p_cap"][p] / D["p_time"][(p, k)]))
    for p in P:
        for d in Dd:
            for k in K:
                add(("sd", p, d, k), D["mat_ship"][k] * D["dist"][(p, d)] - D["d_price"][(d, k)], D["d_demand"][(d, k)])

    n = len(names)
    rows, lo, hi = [], [], []
    A = lil_matrix((10000, n))
    r = 0

    def con(coefs, l, h):
        nonlocal r
        for key, v in coefs:
            A[r, idx[key]] = v
        lo.append(l); hi.append(h); r += 1

    for s in S:
        for m in M:
            con([(("ms", s, p, m), 1) for p in P], -np.inf, D["s_max"][(s, m)] * 10)
    for p in P:
        for m in M:
            c = [(("ms", s, p, m), 1) for s in S] + [(("mk", p, k), -10 * D["req"][(k, m)]) for k in K]
            con(c, 0, np.inf)
        con([(("mk", p, k), D["p_time"][(p, k)]) for k in K], -np.inf, D["p_cap"][p])
        for k in K:
            con([(("sd", p, d, k), 1) for d in Dd] + [(("mk", p, k), -1)], -np.inf, 0)
    for d in Dd:
        for k in K:
            con([(("sd", p, d, k), 1) for p in P], -np.inf, D["d_demand"][(d, k)])

    A = A[:r].tocsr()
    res = milp(c=np.array(cost), integrality=np.array(integ),
               bounds=Bounds(np.zeros(n), np.array(ub)),
               constraints=LinearConstraint(A, lo, hi),
               options={"time_limit": time_limit, "mip_rel_gap": 0})
    if res.x is None:
        raise RuntimeError(res.message)
    x = np.round(res.x).astype(int)

    sol = {"supply": {}, "ship_sp": {}, "make": {}, "send": {}}
    for (key, v) in zip(names, x):
        if key[0] == "ms":
            _, s, p, m = key
            sol["ship_sp"][(s, p, m)] = v / 10
            sol["supply"][(s, m)] = sol["supply"].get((s, m), 0) + v / 10
        elif key[0] == "mk":
            sol["make"][(key[1], key[2])] = int(v)
        else:
            sol["send"][(key[1], key[2], key[3])] = int(v)
    for s in S:
        for m in M:
            sol["supply"][(s, m)] = round(sol["supply"].get((s, m), 0), 1)
    return sol

def _match(label, D):
    left, right = label.split("\\")
    item = _code(right)
    if "→" in left:
        a, b = left.split("→")
        return a, b, item
    return left, item

def write_solution(D, sol, template, out):
    wb = openpyxl.load_workbook(template)
    ws = wb.active
    for row in ws.iter_rows(min_row=2):
        typ, label = row[0].value, row[1].value
        if typ == "supply":
            s, m = _match(label, D); v = sol["supply"].get((s, m), 0)
        elif typ.startswith("ship (supply"):
            s, p, m = _match(label, D); v = sol["ship_sp"].get((s, p, m), 0)
        elif typ == "process":
            p, k = _match(label, D); v = sol["make"].get((p, k), 0)
        elif typ.startswith("ship (proc"):
            p, d, k = _match(label, D); v = sol["send"].get((p, d, k), 0)
        else:
            continue
        row[2].value = int(v) if float(v).is_integer() else round(float(v), 1)
    wb.save(out)

def read_solution(D, path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    sol = {"supply": {}, "ship_sp": {}, "make": {}, "send": {}}
    for typ, label, q in ws.iter_rows(min_row=2, max_col=3, values_only=True):
        q = float(q or 0)
        if typ == "supply":
            sol["supply"][_match(label, D)] = q
        elif typ.startswith("ship (supply"):
            sol["ship_sp"][_match(label, D)] = q
        elif typ == "process":
            sol["make"][_match(label, D)] = q
        elif typ.startswith("ship (proc"):
            sol["send"][_match(label, D)] = q
    return sol

def report(D, sol):
    print("\nSUPPLY (kg/units)")
    for (s, m), q in sol["supply"].items():
        if q: print(f"  {s:16s} {m:4s} {q:8.1f} / {D['s_max'][(s, m)]:.0f}")
    print("PRODUCTION")
    for p in D["procs"]:
        hrs = sum(sol["make"].get((p, k), 0) * D["p_time"][(p, k)] for k in D["prods"])
        mk = {k: sol["make"].get((p, k), 0) for k in D["prods"]}
        print(f"  {p:20s} {mk}  hours {hrs:.1f}/{D['p_cap'][p]:.0f}")
    print("SALES (sold / demand)")
    for d in D["dists"]:
        for k in D["prods"]:
            got = sum(sol["send"].get((p, d, k), 0) for p in D["procs"])
            if got: print(f"  {d:20s} {k:6s} {got:5.0f} / {D['d_demand'][(d, k)]:.0f}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    D = load_data(sys.argv[1])
    if sys.argv[3] == "--score":
        sol = read_solution(D, sys.argv[4])
        prof, bad = score(D, sol)
        print(f"profit = ${prof:,.2f}")
        print("violations:", bad or "none")
    else:
        sol = optimize(D)
        prof, bad = score(D, sol)
        write_solution(D, sol, sys.argv[2], sys.argv[3])
        report(D, sol)
        print(f"\nPROFIT = ${prof:,.2f}   violations: {bad or 'none'}")
        print(f"wrote {sys.argv[3]}")
