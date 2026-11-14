# Computational Logistics: Supply Chain Optimizer



made for rhs tsa comp logisitcs event below is  a guide on how to use it, how it works, and how we tested it. 


## Setup



    pip install numpy openpyxl scipy





## Usage



    py tool.py "C:\Users\akhil\OneDrive\Desktop\practice\practice\data" "C:\Users\akhil\OneDrive\Desktop\practice\practice\solution - template.xlsx" my_solution.xlsx



- **Data folder**: Contains the six input files (suppliers, processors, distributors, distances, material requirements, shipping costs). It matches files by keyword, so spaces vs. underscores in filenames won't break it.

- **Output**: Fills in the template while keeping its original formatting intact so it's ready to submit, then prints the final profit to the console.



## How It Works



The script (`tool.py`) models the supply chain as a mixed-integer linear program (MILP) and solves it using SciPy's HiGHS solver (`scipy.optimize.milp`) with a 0% optimality gap, guaranteeing the exact global maximum in a couple of seconds.



- Variables (one per template row): raw material shipped (in 0.1 increments), integer units produced at each processor, and integer units shipped to distributors.

- Objective: Maximize revenue minus supplier, processing, and shipping costs.

- Constraints: Respects supplier monthly caps, processor hour limits, distributor demand ceilings, and material/inventory flow balances.



## Validation



- Hand-checked exemplars: Confirmed our cost logic against both exemplar solutions—matched $2,875.50 (A) and $687.35 (B) to the cent, verifying that all purchased/shipped material is billed even if left unused.

- Sample data: Hit $54,716.94, matching the early-posting leaderboard.

- Stress test: Ran a modified practice dataset with altered costs, capacities, and demand; returned a valid, constraint-clean profit of $49,033.78.
