from __future__ import annotations

import copy
import inspect
from dataclasses import fields, is_dataclass, replace

import pandas as pd
import plotly.express as px
import streamlit as st

from simulator.models import TaskSpec
from simulator.simulation import DEFAULT_TASKS, SimulationResult, run_simulation

POLICIES = ["FCFS", "Strict Priority", "Priority + PIP + Aging"]
NAV_ITEMS = ["Overview", "Patient Queue", "Operating Rooms", "Medical Teams", "Equipment", "Surgery Schedule", "OS Scheduler", "Analytics", "About the Project"]


@st.cache_data(show_spinner=False)
def cached_simulation(policy: str, specs: tuple[TaskSpec, ...]) -> SimulationResult:
    return run_simulation(policy, list(specs))


DEFAULT_SCENARIO = "Default scenario"
CHALLENGE_OPTIONS = [
    "C1 · SurgiQueue trace oracle",
    "C2 · Equal-priority ties",
    "C3 · Aging under arrivals",
    "C4 · Reset while blocked",
    "C5 · Nested priority donation",
]

# These fixtures use the values in the KO-18 challenge handout. C2 uses an
# explicit arrival tick for T3 so the owner has time to acquire R1 before T3
# requests it. C4 deliberately reuses C1's workload; the current engine has no
# pause/step API with which to interrupt a live run at logical tick 2.
CHALLENGE_TASK_DATA: dict[str, list[dict]] = {
    CHALLENGE_OPTIONS[0]: [
        {"task_id": "P3", "name": "Low-priority R1 owner", "priority": 1, "arrival_time": 0, "cpu_burst": 3, "resource_id": "R1", "lock_request_at": 0, "lock_hold_ticks": 3},
        {"task_id": "P1", "name": "High-priority R1 requester", "priority": 3, "arrival_time": 1, "cpu_burst": 1, "resource_id": "R1", "lock_request_at": 0, "lock_hold_ticks": 1},
        {"task_id": "P2", "name": "Medium-priority CPU task", "priority": 2, "arrival_time": 2, "cpu_burst": 4},
    ],
    CHALLENGE_OPTIONS[1]: [
        {"task_id": "T1", "name": "Equal-priority task 1 / R1 owner", "priority": 2, "arrival_time": 0, "cpu_burst": 2, "resource_id": "R1", "lock_request_at": 0, "lock_hold_ticks": 2},
        {"task_id": "T2", "name": "Equal-priority task 2", "priority": 2, "arrival_time": 0, "cpu_burst": 2},
        {"task_id": "T3", "name": "Higher-priority task blocked on R1", "priority": 3, "arrival_time": 1, "cpu_burst": 1, "resource_id": "R1", "lock_request_at": 0, "lock_hold_ticks": 1},
    ],
    CHALLENGE_OPTIONS[2]: [
        {"task_id": "L", "name": "Low-priority task protected by aging", "priority": 1, "arrival_time": 0, "cpu_burst": 1},
        *[
            {"task_id": f"U{i}", "name": f"Continuous arrival U{i}", "priority": 3, "arrival_time": i, "cpu_burst": 1}
            for i in range(10)
        ],
    ],
    CHALLENGE_OPTIONS[3]: [
        {"task_id": "P3", "name": "Low-priority R1 owner", "priority": 1, "arrival_time": 0, "cpu_burst": 3, "resource_id": "R1", "lock_request_at": 0, "lock_hold_ticks": 3},
        {"task_id": "P1", "name": "High-priority R1 requester", "priority": 3, "arrival_time": 1, "cpu_burst": 1, "resource_id": "R1", "lock_request_at": 0, "lock_hold_ticks": 1},
        {"task_id": "P2", "name": "Medium-priority CPU task", "priority": 2, "arrival_time": 2, "cpu_burst": 4},
    ],
}

# Alternative names let the UI adapt to the TaskSpec field names used by the
# project's simulator package. If resource timing fields do not exist, the app
# reports that limitation instead of claiming it ran a lock-contention test.
TASK_FIELD_ALIASES = {
    "task_id": ("task_id", "id", "pid"),
    "name": ("name", "task_name", "label"),
    "priority": ("base_priority", "priority", "initial_priority"),
    "arrival_time": ("arrival_time", "arrival_tick", "arrival", "release_time"),
    "cpu_burst": ("cpu_burst", "burst_time", "burst", "total_cpu", "cpu_time", "cpu_ticks", "execution_time"),
    "resource_id": ("resource_id", "lock_resource", "resource", "resource_name", "lock_name", "mutex_name"),
    "lock_request_at": ("lock_request_at", "resource_request_at", "lock_at", "lock_request_tick", "resource_request_tick", "request_at", "acquire_lock_at", "lock_start_tick"),
    "lock_hold_ticks": ("lock_hold_ticks", "lock_duration", "resource_hold_time", "critical_section_ticks", "critical_section_duration", "lock_hold", "resource_hold", "hold_ticks"),
}
LOCK_REQUEST_FIELDS = set(TASK_FIELD_ALIASES["lock_request_at"])
LOCK_HOLD_FIELDS = set(TASK_FIELD_ALIASES["lock_hold_ticks"])


def _task_spec_field_names(template: TaskSpec) -> set[str]:
    names: set[str] = set()
    if is_dataclass(template):
        names.update(field.name for field in fields(template))
    try:
        names.update(inspect.signature(type(template)).parameters.keys())
    except (TypeError, ValueError):
        pass
    try:
        names.update(vars(template).keys())
    except TypeError:
        pass
    return names


def _build_task_spec(template: TaskSpec, task_data: dict) -> TaskSpec:
    available = _task_spec_field_names(template)
    updates: dict = {}
    for logical_name in ("task_id", "name", "priority", "arrival_time", "cpu_burst"):
        candidate = next((field_name for field_name in TASK_FIELD_ALIASES[logical_name] if field_name in available), None)
        if candidate is None:
            raise ValueError(
                f"The simulator's TaskSpec does not expose a recognized field for '{logical_name}'. "
                "Provide simulator/models.py so the challenge fixture can be mapped exactly."
            )
        updates[candidate] = task_data[logical_name]

    uses_lock = "lock_request_at" in task_data
    request_field = next((name for name in TASK_FIELD_ALIASES["lock_request_at"] if name in available), None)
    hold_field = next((name for name in TASK_FIELD_ALIASES["lock_hold_ticks"] if name in available), None)
    resource_field = next((name for name in TASK_FIELD_ALIASES["resource_id"] if name in available), None)
    if uses_lock and (request_field is None or hold_field is None):
        raise ValueError(
            "This simulator's TaskSpec does not expose both a lock-request timing field and a critical-section duration field. "
            "The sample is available for reference, but it cannot safely be run as a resource-contention simulation."
        )

    # Explicitly clear inherited lock settings on cloned templates for tasks
    # that do not use R1, so an unrelated default task cannot contaminate a test.
    if request_field is not None:
        updates[request_field] = task_data.get("lock_request_at", None)
    if hold_field is not None:
        updates[hold_field] = task_data.get("lock_hold_ticks", 0)
    if resource_field is not None:
        updates[resource_field] = task_data.get("resource_id", None)

    if is_dataclass(template):
        return replace(template, **updates)
    cloned = copy.copy(template)
    try:
        for field_name, value in updates.items():
            setattr(cloned, field_name, value)
    except (AttributeError, TypeError) as exc:
        raise ValueError(f"Cannot update TaskSpec fields for this simulator: {exc}") from exc
    return cloned


def build_challenge_specs(challenge_name: str) -> list[TaskSpec]:
    if challenge_name == CHALLENGE_OPTIONS[4]:
        raise NotImplementedError(
            "C5 needs two independent locks and transitive priority inheritance. The current simulator exposes only one shared resource (R1)."
        )
    data_rows = CHALLENGE_TASK_DATA[challenge_name]
    if not DEFAULT_TASKS:
        raise ValueError("No default TaskSpec is available to use as a template.")
    template = DEFAULT_TASKS[0]
    return [_build_task_spec(template, row) for row in data_rows]


def load_challenge_workload(challenge_name: str, policy: str) -> bool:
    """Load a selected fixture as the shared workload for Scheduler and Analytics."""
    st.session_state.active_challenge = challenge_name
    st.session_state.challenge_supported = False
    st.session_state.challenge_error = None
    try:
        if challenge_name == DEFAULT_SCENARIO:
            new_specs = list(DEFAULT_TASKS)
        else:
            new_specs = build_challenge_specs(challenge_name)
        new_result = cached_simulation(policy, tuple(new_specs))
    except Exception as exc:
        st.session_state.challenge_error = str(exc)
        return False

    st.session_state.specs = new_specs
    st.session_state.result = new_result
    st.session_state.challenge_supported = True
    st.session_state.challenge_error = None
    return True


def default_patients() -> list[dict]:
    return [
        {"Patient ID": "DEMO-1042", "Procedure": "Orthopedic repair", "Status": "Scheduled", "Room": "OR-2", "Time": "08:30", "Department": "Orthopedics"},
        {"Patient ID": "DEMO-1043", "Procedure": "General surgery", "Status": "In progress", "Room": "OR-1", "Time": "09:15", "Department": "General Surgery"},
        {"Patient ID": "DEMO-1044", "Procedure": "Ophthalmic procedure", "Status": "Ready for room", "Room": "OR-3", "Time": "10:00", "Department": "Ophthalmology"},
    ]


def style_page() -> None:
    st.set_page_config(page_title="SurgiQueue", page_icon="+", layout="wide", initial_sidebar_state="expanded")
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Space+Grotesk:wght@400;500;600;700&display=swap');
    :root { --navy:#102333; --teal:#0e9f9a; --ink:#172b3a; --muted:#647889; --line:#d9e4e9; --red:#c94c5b; --amber:#c48713; --green:#22875a; }
    html, body, [class*="css"] { font-family:'Space Grotesk', sans-serif; color:var(--ink); }
    .stApp { background:#f5f8fa; }
    [data-testid="stSidebar"] { background:var(--navy); }
    [data-testid="stSidebar"] * { color:#e6f0f2; }
    h1,h2,h3 { color:var(--navy); letter-spacing:0; }
    .eyebrow { color:var(--teal); font-family:'DM Mono',monospace; font-size:.72rem; letter-spacing:.12em; text-transform:uppercase; }
    .lede { color:var(--muted); font-size:1rem; max-width:760px; }
    .demo-label { display:inline-block; color:#8a4f00; background:#fff1d2; border:1px solid #f0cc82; border-radius:4px; padding:.25rem .5rem; font:500 .7rem 'DM Mono',monospace; letter-spacing:.08em; }
    .card { background:white; border:1px solid var(--line); border-radius:8px; padding:1rem; box-shadow:0 2px 8px rgba(16,35,51,.04); }
    .metric { background:white; border:1px solid var(--line); border-top:3px solid var(--teal); border-radius:8px; padding:.9rem; min-height:92px; }
    .metric-label { color:var(--muted); font-size:.76rem; }
    .metric-value { color:var(--navy); font:500 1.55rem 'DM Mono',monospace; margin-top:.3rem; }
    .stButton > button { border-radius:5px; font-weight:600; }
    </style>
    """, unsafe_allow_html=True)


def metric_card(label: str, value: str) -> None:
    st.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)


def timeline_chart(result: SimulationResult):
    frame = pd.DataFrame(result.timeline)
    if frame.empty:
        return None
    rows = []
    for task_id in frame["Task"].unique():
        task_frame = frame[frame["Task"] == task_id].sort_values("Tick")
        for _, row in task_frame.iterrows():
            rows.append({"Task": task_id, "State": row["State"], "Start": row["Tick"], "Finish": row["Tick"] + 1, "Effective priority": row["Effective priority"]})
    chart = px.timeline(pd.DataFrame(rows), x_start="Start", x_end="Finish", y="Task", color="State", hover_data=["Effective priority"], color_discrete_map={"RUNNING":"#0e9f9a", "READY":"#e3a632", "BLOCKED":"#c94c5b", "COMPLETED":"#5b7c92", "NEW":"#cbd7dd"})
    chart.update_yaxes(autorange="reversed", title=None)
    chart.update_xaxes(title="Logical tick", dtick=1)
    chart.update_layout(height=330, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="")
    return chart


def event_frame(result: SimulationResult) -> pd.DataFrame:
    return pd.DataFrame([{"Time": event.time, "Type": event.event_type, "Task": event.task_id or "", "Resource": event.resource_id or "", "Explanation": event.explanation} for event in result.events])


def render_overview() -> None:
    st.markdown('<div class="eyebrow">SurgiQueue / hospital operations</div>', unsafe_allow_html=True)
    st.title("Hospital Operations Dashboard")
    st.markdown('<span class="demo-label">DEMO ENVIRONMENT — SIMULATED DATA</span>', unsafe_allow_html=True)
    st.markdown('<p class="lede">A fictional operations view paired with a real, deterministic operating-systems scheduling laboratory.</p>', unsafe_allow_html=True)
    patients = st.session_state.patients
    rooms = st.session_state.rooms
    cols = st.columns(4)
    values = [len(patients), sum(room["Status"] == "Available" for room in rooms), sum(room["Status"] == "In Use" for room in rooms), len([event for event in st.session_state.result.events if event.event_type == "PRIORITY_INVERSION_DETECTED"])]
    for column, label, value in zip(cols, ["Scheduled procedures", "Available operating rooms", "Resources in use", "Active scheduling alerts"], values):
        with column:
            metric_card(label, str(value))
    st.markdown("### Operating-room status")
    room_cols = st.columns(len(rooms))
    for column, room in zip(room_cols, rooms):
        with column:
            color = {"Available":"#22875a", "In Use":"#c48713", "Maintenance":"#c94c5b"}.get(room["Status"], "#647889")
            st.markdown(f'<div class="card"><b>{room["ID"]}</b><p style="color:{color};font-weight:600">{room["Status"]}</p><small>{room["Procedure"] or "No procedure assigned"}</small></div>', unsafe_allow_html=True)
    st.markdown("### Upcoming procedures")
    st.dataframe(pd.DataFrame(patients), width="stretch", hide_index=True)
    if st.button("Open OS Scheduling Simulator", type="primary"):
        st.session_state.pending_nav = "OS Scheduler"
        st.rerun()


def render_patient_queue() -> None:
    st.markdown('<div class="eyebrow">Fictional workflow records</div>', unsafe_allow_html=True)
    st.title("Patient Queue")
    st.warning("Demo records only. Patient status is a workflow label and does not change OS task priority or scheduling decisions.")

    with st.form("demo_patient"):
        a, b, c = st.columns(3)
        patient_id = a.text_input("Demo patient ID", placeholder="DEMO-2001")
        procedure = b.text_input("Procedure category", placeholder="General surgery")
        department = c.selectbox("Department", ["General Surgery", "Orthopedics", "Ophthalmology"])
        if st.form_submit_button("Add demo patient"):
            if not patient_id.strip().startswith("DEMO-") or not procedure.strip():
                st.error("Use a fictional ID beginning with DEMO- and provide a procedure category.")
            elif any(patient["Patient ID"] == patient_id.strip() for patient in st.session_state.patients):
                st.error("That demo patient ID already exists. Please use a unique ID.")
            else:
                st.session_state.patients.append({"Patient ID": patient_id.strip(), "Procedure": procedure.strip(), "Status": "Scheduled", "Room": "Unassigned", "Time": "Pending", "Department": department})
                st.success("Demo patient added.")

    st.markdown("### Change patient status")
    status_options = ["Scheduled", "Ready for room", "In progress", "Completed", "On hold", "Cancelled"]
    patients = st.session_state.patients
    if patients:
        with st.form("update_patient_status"):
            left, middle, right = st.columns([2, 2, 1])
            selected_patient_id = left.selectbox(
                "Select demo patient",
                options=[patient["Patient ID"] for patient in patients],
                format_func=lambda patient_id: next(
                    (f"{patient_id} — {patient['Procedure']}" for patient in patients if patient["Patient ID"] == patient_id),
                    patient_id,
                ),
            )
            current_patient = next(patient for patient in patients if patient["Patient ID"] == selected_patient_id)
            available_statuses = list(dict.fromkeys(status_options + [current_patient["Status"]]))
            new_status = middle.selectbox(
                "New status",
                available_statuses,
                index=available_statuses.index(current_patient["Status"]),
            )
            submitted = right.form_submit_button("Update status", type="primary")
            if submitted:
                current_patient["Status"] = new_status
                st.success(f"{selected_patient_id} status updated to '{new_status}'.")
    else:
        st.info("Add a demo patient first to change a status.")

    left, right = st.columns([1, 2])
    search = left.text_input("Search patient ID")
    status_filter = right.multiselect("Filter status", sorted({patient["Status"] for patient in st.session_state.patients}))
    frame = pd.DataFrame(st.session_state.patients)
    if search:
        frame = frame[frame["Patient ID"].str.contains(search, case=False, na=False)]
    if status_filter:
        frame = frame[frame["Status"].isin(status_filter)]
    st.dataframe(frame, width="stretch", hide_index=True)


def render_rooms(kind: str) -> None:
    st.markdown('<div class="eyebrow">Hospital operations context</div>', unsafe_allow_html=True)
    st.title(kind)
    if kind == "Operating Rooms":
        for room in st.session_state.rooms:
            room["Status"] = st.selectbox(room["ID"], ["Available", "In Use", "Maintenance"], index=["Available", "In Use", "Maintenance"].index(room["Status"]), key=f"room_{room['ID']}")
        st.dataframe(pd.DataFrame(st.session_state.rooms), width="stretch", hide_index=True)
    elif kind == "Medical Teams":
        st.dataframe(pd.DataFrame([
            {"Team": "Team A", "Specialty": "General Surgery", "Status": "On call", "Assigned room": "OR-1"},
            {"Team": "Team B", "Specialty": "Orthopedics", "Status": "Available", "Assigned room": "OR-2"},
            {"Team": "Team C", "Specialty": "Ophthalmology", "Status": "Available", "Assigned room": "OR-3"},
        ]), width="stretch", hide_index=True)
    else:
        st.dataframe(pd.DataFrame([
            {"Equipment": "Imaging cart A", "Status": "Available", "Location": "Equipment bay"},
            {"Equipment": "Instrument set B", "Status": "In use", "Location": "OR-1"},
            {"Equipment": "Anesthesia workstation C", "Status": "Maintenance", "Location": "Service"},
        ]), width="stretch", hide_index=True)


def render_schedule() -> None:
    st.markdown('<div class="eyebrow">Fictional operational plan</div>', unsafe_allow_html=True)
    st.title("Surgery Schedule")
    st.dataframe(pd.DataFrame(st.session_state.patients).sort_values("Time"), width="stretch", hide_index=True)
    st.info("Scheduling entries are fictional workflow records. The OS laboratory demonstrates software scheduling, not surgery prioritisation.")


def render_challenge_samples() -> None:
    """Show reference datasets for the five assigned OSH004 challenge options."""
    st.markdown("### Five OSH004 challenge sample datasets")
    st.caption(
        "These synthetic fixtures are also selectable workloads. Use the challenge loader below to make a supported fixture "
        "the active OS Scheduler run; Analytics will then use the same loaded task list."
    )

    challenge_tabs = st.tabs([
        "C1 · Trace oracle",
        "C2 · Equal-priority ties",
        "C3 · Aging",
        "C4 · Reset while blocked",
        "C5 · Nested donation",
    ])

    with challenge_tabs[0]:
        st.markdown("**KO-18-C1 — SurgiQueue trace oracle (Easy)**")
        st.write("Run strict priority and PIP-only on the same workload before adding aging. Compare blocked and completion times.")
        st.dataframe(pd.DataFrame([
            {"Task": "P3", "Base priority": 1, "Arrival tick": 0, "Sample CPU/resource data": "Owns R; critical section lasts 3 ticks", "Lock behavior": "Acquire R; lock request takes 0 ticks"},
            {"Task": "P1", "Base priority": 3, "Arrival tick": 1, "Sample CPU/resource data": "Needs R for 1 tick", "Lock behavior": "Requests R; becomes BLOCKED while P3 owns it"},
            {"Task": "P2", "Base priority": 2, "Arrival tick": 2, "Sample CPU/resource data": "CPU burst = 4 ticks", "Lock behavior": "No resource use specified"},
        ]), width="stretch", hide_index=True)
        st.info("Validate: under strict priority, P2 can delay low-priority P3 while high-priority P1 is blocked. Under PIP-only, P3 should inherit P1's effective priority while holding R, helping it release R sooner. Record actual times from the event log.")

    with challenge_tabs[1]:
        st.markdown("**KO-18-C2 — Equal-priority deterministic ties (Medium)**")
        st.write("Replay the same workload twice and confirm a deterministic tie-break rule. BLOCKED tasks must not be eligible for CPU dispatch.")
        st.dataframe(pd.DataFrame([
            {"Task": "T1", "Base priority": 2, "Arrival tick": 0, "CPU burst": 2, "Initial state / note": "READY; task ID 1"},
            {"Task": "T2", "Base priority": 2, "Arrival tick": 0, "CPU burst": 2, "Initial state / note": "READY; task ID 2"},
            {"Task": "T3", "Base priority": 3, "Arrival tick": "Not specified", "CPU burst": "Not specified", "Initial state / note": "BLOCKED while waiting for resource R"},
        ]), width="stretch", hide_index=True)
        st.info("Expected rule in this UI: choose the READY task with the highest effective priority; ties go to earlier arrival, then task ID. T1 should win the T1/T2 tie because task ID 1 is lower. T3 must not be chosen while BLOCKED, despite its higher priority.")

    with challenge_tabs[2]:
        st.markdown("**KO-18-C3 — Aging under continuous arrivals (Medium)**")
        st.write("Show that aging protects an ordinary READY task from starvation while avoiding incorrect priority changes for mutex-BLOCKED tasks.")
        aging_rows = [{
            "Task": "L", "Base priority": 1, "Arrival tick": 0, "CPU burst": "Not specified",
            "Rule / note": "Initially READY; effective priority increases by 1 per READY waiting tick"
        }]
        aging_rows.extend({
            "Task": f"U{i}", "Base priority": 3, "Arrival tick": i, "CPU burst": 1,
            "Rule / note": "New higher-priority arrival"
        } for i in range(10))
        st.dataframe(pd.DataFrame(aging_rows), width="stretch", hide_index=True)
        st.caption("Tie rule: earlier arrival wins. Aging increases priority by 1 per tick spent READY; do not apply READY aging while a task is BLOCKED on a mutex.")
        st.info("Validate: inspect L's effective-priority history as U0–U9 arrive. L should eventually compete successfully for CPU time due to aging. Capture the relevant READY/effective-priority events.")

    with challenge_tabs[3]:
        st.markdown("**KO-18-C4 — Reset during blocked state (Hard)**")
        st.write("Reuse the Challenge 1 workload and interrupt the run at logical tick 2 while P1 is blocked and P3 has inherited priority.")
        st.dataframe(pd.DataFrame([
            {"Check point": "Before reset", "Expected sample state": "P1 = BLOCKED on R; P3 owns R and is boosted under PIP", "Inspect" : "Resource owner, waiters, base/effective priorities"},
            {"Action": "Reset", "Expected sample state": "Discard all transient run state", "Inspect": "Owner cleared; waiting list cleared; inherited priority removed"},
            {"Action": "Rerun PIP-only", "Expected sample state": "Fresh execution from tick 0", "Inspect": "Events and metrics are reproducible; no stale owner/waiter remains"},
        ]), width="stretch", hide_index=True)
        st.info("This is a state-recovery test, not just a visual reset: confirm the lock owner, resource wait queue, task states, and effective priorities are reinitialized before rerunning.")

    with challenge_tabs[4]:
        st.markdown("**KO-18-C5 — Nested donation extension (Hard)**")
        st.write("Exercise transitive priority inheritance across two locks, with finite critical sections.")
        st.dataframe(pd.DataFrame([
            {"Task": "L", "Base priority": 1, "Lock owned": "A", "Waiting for": "None initially", "Sample behavior": "Low-priority task holds A"},
            {"Task": "M", "Base priority": 2, "Lock owned": "B", "Waiting for": "A", "Sample behavior": "Owns B but blocks trying to acquire A"},
            {"Task": "H", "Base priority": 3, "Lock owned": "None", "Waiting for": "B", "Sample behavior": "High-priority task blocks waiting for B"},
        ]), width="stretch", hide_index=True)
        st.warning("Backend requirement: the current dashboard view exposes one shared resource (R1). This sample describes the required two-lock extension (A and B); it will need simulator support for lock graphs and transitive donation before it can be run end-to-end.")
        st.info("Validate: H's priority should propagate to M and then L while the dependency chain exists. Recompute effective priorities from current donations when locks are released; do not blindly reset them to base priority.")


def render_scheduler() -> None:
    st.markdown('<div class="eyebrow">Operating systems laboratory</div>', unsafe_allow_html=True)
    st.title("OS Scheduler")
    st.markdown('<p class="lede">Visualise task scheduling, shared-resource contention, priority inversion, and mitigation through Priority Inheritance.</p>', unsafe_allow_html=True)

    # Put the dataset selector at the top so it is immediately visible without
    # scrolling through the challenge reference tables.
    st.markdown("### 1. Choose and load a challenge")
    selected_challenge = st.selectbox(
        "Select challenge dataset",
        [DEFAULT_SCENARIO, *CHALLENGE_OPTIONS],
        key="challenge_selector",
        help="The loaded workload is shared by the OS Scheduler and Analytics.",
    )
    load_col, policy_col, active_col = st.columns([1, 1, 2])
    with load_col:
        load_clicked = st.button("Load selected dataset", type="primary", key="load_challenge_scheduler")
    with policy_col:
        policy = st.selectbox("Scheduling policy", POLICIES, index=POLICIES.index(st.session_state.policy), key="scheduler_policy")
        st.session_state.policy = policy
    if load_clicked:
        succeeded = load_challenge_workload(selected_challenge, policy)
        if succeeded:
            st.success(f"Loaded {selected_challenge}. The OS Scheduler and Analytics now use this workload.")
        else:
            st.error(
                f"Could not load {selected_challenge}: "
                + (st.session_state.get("challenge_error") or "No compatible simulation backend is available.")
            )
    with active_col:
        st.markdown(f"**Active workload:** {st.session_state.get('active_challenge', DEFAULT_SCENARIO)}")
        if st.session_state.get("challenge_supported", True):
            st.caption("Run the simulation below. Analytics automatically uses this active workload.")
        else:
            st.warning("This challenge is not runnable with the current simulator backend. See the error above.")

    st.markdown("**Priority convention:** larger numerical values represent higher priority. FCFS selects the earliest-arriving task. Under a priority policy, the READY task with the highest effective priority is selected; if priorities are equal, earlier arrival wins, then task ID breaks any remaining tie. Each tick reevaluates READY tasks.")
    st.divider()
    render_challenge_samples()
    st.divider()
    st.markdown("### 2. Run the active workload")
    st.info("Patient status changes in the Patient Queue are independent of this OS lab. They do not change a task's base/effective priority.")
    if not st.session_state.get("challenge_supported", True):
        st.info("The execution trace below is hidden because it would belong to the previous runnable workload, not the selected challenge. Choose a supported dataset or the default scenario to run again.")
        return

    if st.button("Run Simulation", type="secondary", key="run_active_simulation"):
        st.session_state.result = cached_simulation(policy, tuple(st.session_state.specs))
    if st.button("Reset / rerun active workload", key="reset_active_simulation"):
        st.session_state.result = cached_simulation(policy, tuple(st.session_state.specs))
    result = st.session_state.result
    cols = st.columns(len(result.tasks))
    for column, task in zip(cols, result.tasks):
        with column:
            waiting = next((event.resource_id for event in result.events if event.event_type == "LOCK_REQUEST_BLOCKED" and event.task_id == task.task_id), "")
            st.markdown(f'<div class="card"><b>{task.task_id} — {task.spec.name}</b><p>Base: {task.base_priority} · Effective: {task.effective_priority}</p><p>State: <b>{task.state.value}</b></p><p>Remaining CPU: {task.remaining_cpu}</p><p>{"Waiting for: " + waiting if waiting else "Resource: none"}</p></div>', unsafe_allow_html=True)
    st.markdown("### Shared resource R1")
    owner = result.resource.owner or "Available"
    st.markdown(f'<div class="card"><b>Lock status:</b> {"LOCKED" if result.resource.locked else "AVAILABLE"} &nbsp; <b>Owner:</b> {owner} &nbsp; <b>Waiting:</b> {", ".join(result.resource.waiting_tasks) or "None"}</div>', unsafe_allow_html=True)
    if result.metrics["inversion_duration"] > 0:
        st.error(f"PRIORITY INVERSION DETECTED · duration {result.metrics['inversion_duration']:.0f} tick(s). A high-priority task was blocked while medium-priority work ran and the low-priority owner was delayed.")
    else:
        st.success("No confirmed priority inversion in this execution trace.")
    st.markdown("### Execution timeline")
    chart = timeline_chart(result)
    if chart:
        st.plotly_chart(chart, width="stretch", config={"displayModeBar": False})
    mcols = st.columns(5)
    for column, label, value in zip(mcols, ["Ready wait", "Blocked time", "Turnaround", "Inversion duration", "Resource utilisation"], [result.metrics["average_ready_wait"], result.metrics["total_blocked_time"], result.metrics["average_turnaround"], result.metrics["inversion_duration"], result.metrics["resource_utilisation"]]):
        with column:
            metric_card(label, f"{value:.2f}")
    st.markdown("### Event log")
    events = event_frame(result)
    event_filter = st.multiselect("Event types", sorted(events["Type"].unique()), default=sorted(events["Type"].unique()))
    filtered = events[events["Type"].isin(event_filter)]
    st.dataframe(filtered, width="stretch", hide_index=True)
    st.download_button("Download event log CSV", filtered.to_csv(index=False), "surgiqueue-events.csv", "text/csv")


def render_analytics() -> None:
    st.markdown('<div class="eyebrow">Policy comparison</div>', unsafe_allow_html=True)
    st.title("Analytics")
    active_challenge = st.session_state.get("active_challenge", DEFAULT_SCENARIO)
    st.markdown(f"**Active workload:** {active_challenge}")
    st.caption("Analytics automatically uses the workload loaded in OS Scheduler. To change datasets, return to OS Scheduler and use the selector at the top of that page.")
    if not st.session_state.get("challenge_supported", True):
        st.warning(
            "Analytics are not calculated for this challenge because the current simulator cannot run its data safely. "
            + (st.session_state.get("challenge_error") or "")
        )
        st.info("C5 needs a two-lock backend for transitive priority inheritance. For any fixture mapping error, add the simulator/model fields required by that challenge before interpreting metrics.")
        unavailable = pd.DataFrame([{
            "Policy": policy,
            "average_ready_wait": "N/A",
            "total_blocked_time": "N/A",
            "average_turnaround": "N/A",
            "inversion_duration": "N/A",
            "resource_utilisation": "N/A",
        } for policy in POLICIES])
        st.dataframe(unavailable, width="stretch", hide_index=True)
        st.caption("No metrics are fabricated: unavailable rows mean this workload has not been executed by the active simulation backend.")
        return

    if active_challenge == CHALLENGE_OPTIONS[3]:
        st.info("C4 uses the C1 task workload for comparison. These metrics describe that workload; the current batch simulator cannot pause at tick 2, so reset-during-BLOCKED-state correctness must still be validated separately.")
    elif active_challenge == CHALLENGE_OPTIONS[0]:
        st.info("C1's fixture is loaded. Available policies are FCFS, Strict Priority, and Priority + PIP + Aging; the current UI does not expose a separate PIP-only policy.")

    rows = []
    for policy in POLICIES:
        try:
            result = cached_simulation(policy, tuple(st.session_state.specs))
            rows.append({"Policy": policy, **result.metrics})
        except Exception as exc:
            st.error(f"Could not compute Analytics for {policy}: {exc}")
            return
    frame = pd.DataFrame(rows)
    st.dataframe(frame, width="stretch", hide_index=True)
    left, right = st.columns(2)
    with left:
        st.plotly_chart(px.bar(frame, x="Policy", y="average_ready_wait", color="Policy", title="Average READY wait"), width="stretch")
    with right:
        st.plotly_chart(px.bar(frame, x="Policy", y="inversion_duration", color="Policy", title="Priority inversion duration"), width="stretch")
    st.caption("All charts and metrics above use the same active task list shown in the OS Scheduler.")
    st.download_button("Download policy metrics CSV", frame.to_csv(index=False), "surgiqueue-policy-metrics.csv", "text/csv")


def render_about() -> None:
    st.markdown('<div class="eyebrow">Project notes</div>', unsafe_allow_html=True)
    st.title("About SurgiQueue")
    st.markdown("""SurgiQueue demonstrates how an operating-system scheduler handles software tasks competing for an exclusive mutex. The hospital setting supplies fictional operational context; it does not turn patients, rooms, or clinicians into CPU processes or mutexes.
**Priority inversion** occurs when a high-priority software task waits for a resource held by a low-priority task while medium-priority work prevents the owner from running. **Priority Inheritance Protocol** temporarily raises the owner's effective priority. **Aging** is separate: it increases the effective priority of eligible READY work to reduce starvation, but never changes mutex-blocked waiting.

All records, procedures, resources, and measurements are synthetic. This prototype is not a clinical decision-support system and must not make patient triage, treatment, or surgery-allocation decisions.""")


def main() -> None:
    style_page()
    if "pending_nav" in st.session_state:
        st.session_state.nav = st.session_state.pop("pending_nav")
    if "nav" not in st.session_state:
        st.session_state.nav = "Overview"
    if "patients" not in st.session_state:
        st.session_state.patients = default_patients()
    if "rooms" not in st.session_state:
        st.session_state.rooms = [
            {"ID": "OR-1", "Status": "In Use", "Procedure": "General surgery"},
            {"ID": "OR-2", "Status": "Available", "Procedure": ""},
            {"ID": "OR-3", "Status": "In Use", "Procedure": "Ophthalmic procedure"},
            {"ID": "OR-4", "Status": "Maintenance", "Procedure": ""},
            {"ID": "OR-5", "Status": "Available", "Procedure": ""},
        ]
    if "specs" not in st.session_state:
        st.session_state.specs = list(DEFAULT_TASKS)
    if "policy" not in st.session_state:
        st.session_state.policy = "Priority + PIP + Aging"
    if "challenge_selector" not in st.session_state:
        st.session_state.challenge_selector = DEFAULT_SCENARIO
    if "active_challenge" not in st.session_state:
        st.session_state.active_challenge = DEFAULT_SCENARIO
    if "challenge_supported" not in st.session_state:
        st.session_state.challenge_supported = True
    if "challenge_error" not in st.session_state:
        st.session_state.challenge_error = None
    if "result" not in st.session_state:
        st.session_state.result = cached_simulation(st.session_state.policy, tuple(st.session_state.specs))

    with st.sidebar:
        st.markdown('<div class="eyebrow">SurgiQueue</div>', unsafe_allow_html=True)
        st.markdown("## Operations console")
        st.markdown('<span class="demo-label">DEMO DATA</span>', unsafe_allow_html=True)
        st.radio("Navigate", NAV_ITEMS, key="nav")
        st.divider()
        st.caption("Healthcare context only. OS scheduling remains separate from clinical decisions.")

    page = st.session_state.nav
    if page == "Overview":
        render_overview()
    elif page == "Patient Queue":
        render_patient_queue()
    elif page in {"Operating Rooms", "Medical Teams", "Equipment"}:
        render_rooms(page)
    elif page == "Surgery Schedule":
        render_schedule()
    elif page == "OS Scheduler":
        render_scheduler()
    elif page == "Analytics":
        render_analytics()
    else:
        render_about()


if __name__ == "__main__":
    main()
