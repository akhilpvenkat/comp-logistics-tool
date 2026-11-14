import sys, glob, os
import numpy as np
import openpyxl
from scipy.optimize import milp, LinearConstraint, Bounds


def code(label):
    return label.split("(")[-1].strip(") ")


def load(folder, name, coded_cols=False):
    for f in glob.glob(folder + "/*.xlsx"):
        if name in os.path.basename(f).replace(" ", "").replace("_", "").lower():
            rows = list(openpyxl.load_workbook(f, data_only=True).active.iter_rows(values_only=True))
            head = [code(c) if coded_cols else c for c in rows[0][1:]]
            return {code(r[0]): dict(zip(head, r[1:])) for r in rows[1:] if r[0]}


def pick(table, prefix, item=""):
    cols = next(iter(table.values()))
    return [c for c in cols if c.startswith(prefix) and item in c][0]


folder, template, out = sys.argv[1:4]
sup = load(folder, "suppliers")
proc = load(folder, "processors")
mkt = load(folder, "distributors")
miles = load(folder, "distances", True)
req = load(folder, "materialrequirements", True)
rate = {k: list(v.values())[-1] for k, v in load(folder, "shippingcosts").items()}


def hours(p, k):
    return proc[p][pick(proc, "Processing Time", f"({k})")]


wb = openpyxl.load_workbook(template)
rows = list(wb.active.iter_rows(min_row=2))
keys = []
for r in rows:
    typ, label = r[0].value, r[1].value
    left, right = label.split("\\")
    a, _, b = left.partition("→")
    if typ.startswith("ship (supply"):
        kind = "ms"
    elif typ == "process":
        kind = "mk"
    elif typ.startswith("ship (proc"):
        kind = "sd"
    else:
        kind = "s"
    keys.append((kind, a, b, code(right)))

v = [k for k in keys if k[0] != "s"]
suppliers = {k[1] for k in v if k[0] == "ms"}
procs = {k[1] for k in v if k[0] == "mk"}
dists = {k[2] for k in v if k[0] == "sd"}
mats = {k[3] for k in v if k[0] == "ms"}
prods = {k[3] for k in v if k[0] == "mk"}

cost, ub = [], []
for kind, a, b, item in v:
    if kind == "ms":
        cost.append(0.1 * (sup[item][f"Cost ({a})"] + rate[item] * miles[a][b]))
        ub.append(sup[item][f"Max Monthly ({a})"] * 10)
    elif kind == "mk":
        cost.append(hours(a, item) * proc[a]["Cost per Hour"])
        ub.append(proc[a][pick(proc, "Max Capacity")] // hours(a, item))
    else:
        cost.append(rate[item] * miles[a][b] - mkt[b][pick(mkt, "Selling Price", f"({item})")])
        ub.append(mkt[b][pick(mkt, "Max Market Demand", f"({item})")])

A, lo, hi = [], [], []


def add(coef, low, high):
    A.append([coef(x) for x in v])
    lo.append(low)
    hi.append(high)


def balance(x, p, m):
    if x[0] == "ms" and x[2] == p and x[3] == m:
        return 1
    if x[0] == "mk" and x[1] == p:
        return -10 * req[x[3]][m]
    return 0


for s in suppliers:
    for m in mats:
        add(lambda x: x[0] == "ms" and x[1] == s and x[3] == m, -np.inf, sup[m][f"Max Monthly ({s})"] * 10)
for p in procs:
    for m in mats:
        add(lambda x: balance(x, p, m), 0, np.inf)
    add(lambda x: hours(p, x[3]) if x[0] == "mk" and x[1] == p else 0, -np.inf, proc[p][pick(proc, "Max Capacity")])
    for k in prods:
        add(lambda x: (x[0] == "sd" and x[1] == p and x[3] == k) - (x[0] == "mk" and x[1] == p and x[3] == k), -np.inf, 0)
for d in dists:
    for k in prods:
        add(lambda x: x[0] == "sd" and x[2] == d and x[3] == k, -np.inf, mkt[d][pick(mkt, "Max Market Demand", f"({k})")])

res = milp(cost, integrality=np.ones(len(v)), bounds=Bounds(0, ub),
           constraints=LinearConstraint(np.array(A, dtype=float), lo, hi),
           options={"mip_rel_gap": 0})
val = dict(zip(v, np.round(res.x)))

for key, r in zip(keys, rows):
    kind, a, b, item = key
    if kind == "s":
        q = sum(n for k, n in val.items() if k[0] == "ms" and k[1] == a and k[3] == item) / 10
    elif kind == "ms":
        q = val[key] / 10
    else:
        q = val[key]
    q = round(float(q), 1)
    r[2].value = int(q) if q == int(q) else q
wb.save(out)
print(f"profit: ${-res.fun:,.2f}")