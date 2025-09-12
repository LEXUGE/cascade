# Cascade
Cascade is a simple CLI program that helps you turn your todo-list into a well-scheduled calendar. It's like a poorman's [motion](https://usemotion.com).

## Features
- Simple timezone-aware scheduling support.
- Dependency-aware task scheduling. Sensible deadline & priority propagation throughout dependency graph.
- Import external calendars / background tasks and schedule around them.
- Fully local. No cloud. No AI.
- Multi-objective optimization using Google OR-Tools.
- Export to `.ics` and add to your calendar app.

## How does it work
Cascade uses a simple model to schedule your tasks:
1. Each task has an expected time $T_{0}$ to complete and a priority (higher = urgent). We define the maximum utility $U_{0}$ of the task as simply its priority.
2. The expected utility of the task is $U_{0} \cdot P(X< \text{allocated time})$ where $X$ is the actual time taken to complete the task, a random variable with expectation $T_{0}$.
3. Optimizer tries to maximize the total expected utility at the end of the schedule by changing allocated time and shuffle tasks around, while satisfying hard constraints specified by your dependency graph and external calendars.
4. Upon schedules with the same total expected utility. We look at the "cumulative utility function" (CUF) which is a function over time on how much utility we have got up to some time $t$. And optimizer tries to find the schedule with largest integral of CUF. This means for two different CUFs $f, g$, $\int f-g$ is used as a tie-breaker.

In the future it should further optimize the schedule by considering context switching induced in each schedule etc.


## Installation
If you use `nix`, try
```
nix run github:LEXUGE/cascade
```

Otherwise, clone the repo and run
```
uv run cascade
```

## Usage
Currently the only way to use `cascade` is through its simple REPL

```
> import
Successfully imported tasks from /home/foo/cascade-demo.yml
> schedule next_day 2days
Downloading calendar from https://mycalendar.org/cal.ics ...
Schedule for 2025-09-13 00:00:00-07:00 → 2025-09-15 00:00:00-07:00
Total utility: 14.0
Total length: 10:20:00
Task "Learning A" scheduled at 2025-09-13 09:00:00-07:00 → 2025-09-13 09:50:00-07:00. Length: 0:50:00, Utility: 2.0
Task "Finish B" scheduled at 2025-09-13 09:50:00-07:00 → 2025-09-13 11:50:00-07:00. Length: 2:00:00, Utility: 2.0
Task "Task 1" scheduled at 2025-09-13 13:00:00-07:00 → 2025-09-13 13:50:00-07:00. Length: 0:50:00, Utility: 2.0
Task "Task 2" scheduled at 2025-09-13 13:50:00-07:00 → 2025-09-13 14:40:00-07:00. Length: 0:50:00, Utility: 2.0
Task "B Note-taking" scheduled at 2025-09-13 14:40:00-07:00 → 2025-09-13 16:00:00-07:00. Length: 1:20:00, Utility: 2.0
Task "Looking into C" scheduled at 2025-09-13 16:00:00-07:00 → 2025-09-13 17:50:00-07:00. Length: 1:50:00, Utility: 1.0
Task "Task 3" scheduled at 2025-09-13 19:00:00-07:00 → 2025-09-13 19:50:00-07:00. Length: 0:50:00, Utility: 2.0
Task "Misc" scheduled at 2025-09-13 19:50:00-07:00 → 2025-09-13 21:40:00-07:00. Length: 1:50:00, Utility: 1.0
```

And commands are simple:
- `import [<your_todo.yml>]`. This imports your todo list. Once todo-list is successfully imported, you can `import` without path specified to re-import it.
- `schedule <start_time relative to now> <end_time relative to start time>`. For example, `schedule "1 day" "2 days"` will create a 24-hour schedule from the next 24th hour to the next 48th hour.
  - You can use `next_day` in `<start_time>` to specify the beginning of the next day. For example, `schedule next_day "1 day"` will create a 24-hour schedule for tomorrow starting from 00:00.
- `schedule export ics`. Cascade will print out your schedule in `ics` format and you can save it and import to your favorite calendar app.


## Todo-list specification
> [!NOTE]
> For power users, I recommend using tools like [nickel](https://nickel-lang.org/) to organize and generate YAML file instead of writing them by hand.

The file has three sections
- `config`: common configuration (currently only specifies the default timezone).
- `bg`: Specify background tasks and calendars. For example, you can specify lunch/dinner time & sleep schedule. You can also import school timetable through a calendar link so cascade will schedule around your timetable.
- `tasks`: All your tasks.

See the below example for specification.
```yml
config:
  default_tz: America/Your City

bg:
  dinner:
    duration: 1hr 30mins
    schedule: 0 18 * * * # in cron job format. time interpreted using `default_tz`
  school-timetable:
    url: https://your_uni.edu/my-timetable.ics # respects the timezone set by events in calendar.
  lunch:
    duration: 1hr
    schedule: 0 12 * * *
  sleep:
    duration: 9hrs
    schedule: 0 23 * * *

tasks:
# There are two types of tasks:
# - "step": these are "atomic" tasks in the sense they can either be finished or unfinished, cannot be completed halfway.
# - "goal": composite tasks with subtasks.

- name: A basic step task # task name is necessary
  # id: my-id # you can optionally set your own task-id. Otherwise it's gonna be automatically generated as the slug of the task name.
  duration: 1hr # expected completion time
  deadline: 1980-01-01 00:00
  timezone: Europe/Your City # optionally specify the timezone of the deadline.
  status: todo # `todo` or `done`

- name: another task
  priority: 2 # optionally specify the task priority
  duration: 10mins
  status: todo
  deps: # task dependency. This also works for a "goal", and dependency will be propagated.
    before: # specify this task should be completed before the following tasks
    - a-basic-step-task # you can also specify a "goal" here.
    # after: you can also specify after

- name: My Goal # You cannot specify `duration` and `status` for a "goal". A goal is completed iff. all subtasks are done.
  subtasks:
  - a-basic-step-task
  - another-task
```
