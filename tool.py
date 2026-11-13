import sys, glob, os
import numpy as np
import pandas as pd
import openpyxl

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

def _match(label, D):
    left, right = label.split("\\")
    item = _code(right)
    if "→" in left:
        a, b = left.split("→")
        return a, b, item
    return left, item

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

if __name__ == "__main__":
    data = load_data(sys.argv[1])
    solution = read_solution(data, sys.argv[2])
    profit, problems = score(data, solution)
    print(f"profit = ${profit:,.2f}")
    print("violations:", problems or "none")
