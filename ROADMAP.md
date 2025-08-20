# Cascade

Some key philosophies:
- Manage tasks, not calendar
- Context switching is expensive
- Tasks don't commute

## Overview
As a MVP, user would be interacting with the scheduler through a REPL-like console. Fundamentally, the whole system consists of three parts
1. A scheduler which schedules _atomic_ tasks using Google's CP-SAT solver.
2. A prediction model which predicts the probability a given task will complete at different times. The result will be used by the scheduler to predict the length of less obvious tasks and schedule accordingly.
3. A frontend that compiles tasks (e.g. recurring tasks, grouped tasks, or even sleep schedules) and their relevant constraints into _atomic_ tasks alongside their constraints, which are fed into the scheduler. And render the scheduled atomic tasks back into beautiful schedules user can understand.

## Steps

### Compiler
So the first step is to implement the last part, the compiler. To facilitate development, we should simplify things further by ignoring the console part for now and focus entirely on compiling into _atomic_ tasks.

For the moment, we should support a few essential task types only
- `step`: an atomic task.
    - It can either be completed or not completed.
    - It can have a deadline and dependencies on other tasks (either `goal` or `step`). This is implemented through `before` and `after` lists.
    - It can be recurring with a frequency (much like systemd timer) but also allows manual overriding (e.g. I want to skip gym this Friday for Amy's birthday party).
        - recurrence can be `indefinite`, `until`.
        - when having both recurrence and deadline, usually we should ask user to set a relative deadline (however, it would be nice to have a way to override certain occurrences).
    - It can have `priority`? A simple priority implementation will be assign a bigger coefficient to the early/late deadline reward/penalty
    - It can have tags
- `goal`: a task that consists of listOf (`step` or `goal`)
    - A `goal` is complete iff. all subtasks within it are completed.
    - It can also have a deadline. The deadline is enforced by setting all leaf steps deadline by `min(leafDDL, goalDDL)` (essentially another merging, but with merging priority based on DDL itself instead of distance to the leaf node, so no overriding from child).
    - It can be set as recurring, the behaviour is that it sets a "default" frequency for all leaf nodes with merging priority depending on how far the `goal` is from the `step`. The final frequency is a result of merging these frequencies based on priority. This allows, for example, user to set a recurring big task but with some small steps that only need to be done once.
    - It can have tags, they will serve as the default tags for children, and feature a merging behaviour like above.

On scheduling, the compiler will compile all atomic tasks that _needs_ to occur before a given time. By needs to occur, we mean
- all tasks without a deadline will be included.
- recurring tasks with a given frequency would be expanded using time and frequency.

Can goal be implemented through the dependencies resolution engine entirely?

### Other thoughts
https://docs.skedpal.com/board/using-the-board the board prioritization in skedpal seems like a good design

skedpal dependency management seems like a mess to use.

Our priority now is to create an easy to interface text-based todolist format (not exactly YAML) so that tasks are easy to create/split etc.

And figure out how to enforce time mask (hard/soft mask? how to reconcile with existing ideas?)
