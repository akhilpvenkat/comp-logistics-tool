import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from stage1_scorer import load_data, score


def greedy(D):
    S, P, Dd, M, K = D["suppliers"], D["procs"], D["dists"], D["mats"], D["prods"]
    sol = {"supply": {}, "ship_sp": {}, "make": {}, "send": {}}
    supply_left = dict(D["s_max"])
    hours_left = dict(D["p_cap"])
    demand_left = dict(D["d_demand"])

    def cheapest_material_cost(p, k):
        total = 0.0
        for m in M:
            q = D["req"][(k, m)]
            if q == 0:
                continue
            best = min(D["s_cost"][(s, m)] + D["mat_ship"][m] * D["dist"][(s, p)] for s in S)
            total += q * best
        return total

    routes = []
    for p in P:
        for k in K:
            for d in Dd:
                margin = (D["d_price"][(d, k)]
                          - D["mat_ship"][k] * D["dist"][(p, d)]
                          - D["p_time"][(p, k)] * D["p_rate"][p]
                          - cheapest_material_cost(p, k))
                per_hour = margin / D["p_time"][(p, k)]
                routes.append((per_hour, margin, p, k, d))
    routes.sort(reverse=True)

    for per_hour, margin, p, k, d in routes:
        if margin <= 0:
            continue
        n = min(int(hours_left[p] // D["p_time"][(p, k)]), int(demand_left[(d, k)]))
        while n > 0:
            plan = {}
            ok = True
            for m in M:
                need = n * D["req"][(k, m)]
                for s in sorted(S, key=lambda s: D["s_cost"][(s, m)] + D["mat_ship"][m] * D["dist"][(s, p)]):
                    take = min(need, supply_left[(s, m)])
                    if take > 0:
                        plan[(s, m)] = take
                        need -= take
                    if need <= 1e-9:
                        break
                if need > 1e-9:
                    ok = False
                    break
            if ok:
                break
            n -= 1
        if n <= 0:
            continue
        for (s, m), q in plan.items():
            q = round(q + 0.049999, 1)
            supply_left[(s, m)] -= q
            sol["supply"][(s, m)] = round(sol["supply"].get((s, m), 0) + q, 1)
            sol["ship_sp"][(s, p, m)] = round(sol["ship_sp"].get((s, p, m), 0) + q, 1)
        hours_left[p] -= n * D["p_time"][(p, k)]
        demand_left[(d, k)] -= n
        sol["make"][(p, k)] = sol["make"].get((p, k), 0) + n
        sol["send"][(p, d, k)] = sol["send"].get((p, d, k), 0) + n
    return sol


if __name__ == "__main__":
    data = load_data(sys.argv[1])
    solution = greedy(data)
    profit, problems = score(data, solution)
    print(f"greedy profit = ${profit:,.2f}")
    print("violations:", problems or "none")
