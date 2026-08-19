# Household Task Solving Skill

## Operating Principles
- Treat **current observations and admissible actions as authoritative**. Never assume object locations, counts, or container contents from prior tasks or memory.
- Decompose every goal into the same chain: **find object → (transform if needed) → move to destination → place object**.
- Track three things continuously: **inventory**, **visited/unvisited containers**, and **which objects have already been transformed/placed**.

## Decision Procedure
At each step, choose the first action that makes progress:

1. **If goal is already satisfied**, stop.
2. **If holding a correctly transformed target and at the destination**, open the destination if needed, then place the object.
3. **If holding a target that still needs transformation**, go to the required transformer (sink/basin for clean, fridge for cool, heat source for heat), open it if needed, and apply the transform.
4. **If holding an object that is not needed**, put it down in any known open, accessible container or surface before taking the real target.
5. **If at a location whose contents are visible and contain a needed target**, take it.
6. **If at a closed container**, open it.
7. **If carrying nothing and no target is visible**, go to the next unexplored/unexamined location.
8. **Use `examine`/`look`/`inventory`** when uncertain about your current surroundings or held items.

## Search Strategy
- Keep a mental checklist of all receptacles you know about: shelves, cabinets, drawers, countertops, tables, appliances, and unusual holders.
- Mark a location as **examined** only after its contents have actually been revealed, not merely because you arrived there.
- Open every closed container you encounter; closed containers can hide the needed object.
- If an object itself can be a container (e.g., a box), take it and examine it.
- For goals requiring **multiple copies** of the same type, deliver one copy to the destination, then search for the next copy.
- Search **systematically**, not randomly. Visit one unexamined place at a time and avoid returning to known-empty places.

## Transformations
- Each transformation has a prerequisite:
  - **Clean** → must be at the cleaning location (e.g., sink/basin).
  - **Cool** → must be at the cooling location (e.g., fridge).
  - **Heat** → must be at the heating location (e.g., microwave/stove).
- Some transformer containers are initially closed; open them before applying the action.
- The object must be in your inventory before transforming.
- Do not transform an object twice if it is already in the required state.

## Avoiding Redundant Actions
- Do not open an already open container.
- Do not re-visit a container already shown to be empty unless you have reason to believe it changed.
- Do not return to the destination before the object is in hand and correctly transformed.
- Do not pick up objects that are not needed unless carrying them is necessary to access another object.
- Do not place an object at a destination that is closed; open the destination first.

## Recovery Heuristics
- If an action is **not admissible**, check which prerequisite is missing: wrong location, closed container, item not in inventory, or object already in the wrong state. Fix that prerequisite first.
- If the target is not in any searched location, **broaden the search** to less obvious places: near-related furniture, holders, appliances, or containers that were initially closed.
- If you are holding a wrong object and cannot pick up the target, **put the wrong object down in a safe visited location**, then take the target.
- If you lose track of what you have searched, use `look`/`inventory` and restart from your mental checklist.
- If an observation says a container is open but lists no contents, trust that observation and do not keep trying to open or search it.

## Selecting the Next Useful Action
- Every action must be enabled by the current state and move one step along the chain: **find → take → transform → move → place**.
- If no useful action is currently available, the next useful action is usually **moving to another unexamined location**.
- Use current observations to update your state after every action; never rely on a pre-learned plan or fixed object positions.
