## Skill Name

Retrieve–Transform–Place Goal Completion

## When to Use

Tasks that require acquiring one or more objects from the environment, optionally changing a physical state of each object (such as cleanliness or temperature), and placing the object(s) at a specified destination. Applies to single-object and multi-object variants, with or without a transformation stage, and with open or closed destinations.

## Goal Decomposition

Convert the instruction into a final predicate with four parts: target object type, required quantity, required physical state (if any), and destination. Treat paraphrases as equivalent — “make X clean and put it in Y” and “put a clean X in Y” produce the same predicate. Do not assume an object already satisfies a stated state condition just because the requirement is phrased as a property.

The ordering constraints are fixed: acquire before transform; transform before place; locate before navigate; make the destination accessible before placing. Track each required instance separately through the full acquire → transform → place cycle before counting it as complete.

## Procedure

1. Parse the goal into a target condition: object type, count, required state, destination. Keep this predicate explicit and do not substitute partial subgoals for it.
2. Locate the required object by systematic search: inspect visible receptacles, open containers, and move through unvisited rooms until the object appears in observation.
3. Acquire the target object and confirm from feedback that it is actually held.
4. If a state condition is required, check whether the target already satisfies it; if not, locate the correct transformation resource, apply it while holding the target, and verify the state change from observation.
5. Locate the destination; if it is closed or inaccessible, make it accessible before attempting placement.
6. Travel to the destination while holding the prepared target and place it there; confirm from feedback that the object is no longer held.
7. For multi-object tasks, repeat steps 2–6 until the required count of distinct instances is fully placed.
8. Confirm the complete goal predicate — correct objects, correct state, correct count, at the destination — before terminating.

## Decision Rules

- When the target is not visible in the current room, continue systematic search rather than manipulating unrelated objects; absence from one room does not imply absence from the environment.
- When holding a prepared target but the destination is unknown, search for the destination before attempting placement.
- When the destination is closed, open it before placing; placement actions require an accessible receptacle.
- When the target is not yet in the required state, transform it before travelling to the destination, even if the destination is already open.
- When state feedback conflicts with your expectation, treat the observation as authoritative, update your model, and choose a different action rather than retrying the same one.
- When the completed instance count is below the required count, continue the acquire–transform–place cycle for a new distinct instance.
- When the target’s current state is unverified and the goal requires a specific state, inspect the object before planning placement.

## State Tracking

Maintain the following across steps, updating only from confirmed observations:

- the full goal predicate (object type, count, required state, destination);
- whether the target has been located and where;
- whether the target is currently held;
- whether each held instance has been verified in the required state;
- destination identity, location, and accessibility;
- whether each placed instance has been verified at the destination;
- how many distinct instances are complete versus remaining.

## Verification

- Acquisition: confirm the take action’s feedback states the object is now in inventory.
- Transformation: confirm the observation reports the object is in the required state after the clean/cool attempt; do not assume success from issuing the action.
- Accessibility: confirm the destination is reported open before placing.
- Placement: confirm feedback states the object is no longer held and is at the destination.
- Completeness: for multi-object tasks, confirm each distinct instance, not the same object repeatedly, satisfies the goal.
- When feedback is ambiguous or absent, inspect the object, inventory, or destination to gather evidence before proceeding or terminating.

## Recovery

- If the target is not found after searching known areas, expand to other rooms and inspect closed containers and less obvious receptacles, updating location knowledge as you go.
- If transformation fails, re-identify the required transformation type, locate the matching resource, and reapply.
- If placement fails, check destination accessibility first; open the destination if closed, then retry.
- If you realize you are holding the wrong object, return or discard it, locate the correct target, and reapply any required transformation before placing.
- If you are uncertain whether an object is transformed or placed, re-inspect the object or destination before deciding to proceed or stop.
- If partial completion remains in a multi-object task, do not terminate; continue the cycle for the remaining instances.

## Termination

Stop only when all of the following are verified from observations: the required number of distinct target objects is placed at the specified destination; each placed object is in the required state; feedback confirms the objects are no longer in inventory. Do not terminate on the basis of intended actions alone.

## Execution Discipline

- Ground every decision in currently visible or reported information; treat the admissible action list as the true set of legal operations.
- Never treat an issued action as an achieved transition until environment feedback confirms it.
- Do not repeat an action after failure without re-reading the observation and correcting the belief that led to the action.
