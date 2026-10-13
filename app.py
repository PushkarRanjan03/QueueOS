from __future__ import annotations

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
    st.warning("Demo records only. The OS scheduler never uses clinical urgency or patient data to make decisions.")
    with st.form("demo_patient"):
        a, b, c = st.columns(3)
        patient_id = a.text_input("Demo patient ID", placeholder="DEMO-2001")
        procedure = b.text_input("Procedure category", placeholder="General surgery")
        department = c.selectbox("Department", ["General Surgery", "Orthopedics", "Ophthalmology"])
        if st.form_submit_button("Add demo patient"):
            if not patient_id.startswith("DEMO-") or not procedure.strip():
                st.error("Use a fictional ID beginning with DEMO- and provide a procedure category.")
            else:
                st.session_state.patients.append({"Patient ID": patient_id.strip(), "Procedure": procedure.strip(), "Status": "Scheduled", "Room": "Unassigned", "Time": "Pending", "Department": department})
                st.success("Demo patient added.")
    left, right = st.columns([1, 2])
    search = left.text_input("Search patient ID")
    status = right.multiselect("Filter status", sorted({patient["Status"] for patient in st.session_state.patients}))
    frame = pd.DataFrame(st.session_state.patients)
    if search:
        frame = frame[frame["Patient ID"].str.contains(search, case=False, na=False)]
    if status:
        frame = frame[frame["Status"].isin(status)]
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


def render_scheduler() -> None:
    st.markdown('<div class="eyebrow">Operating systems laboratory</div>', unsafe_allow_html=True)
    st.title("OS Scheduler")
    st.markdown('<p class="lede">Visualise task scheduling, shared-resource contention, priority inversion, and mitigation through Priority Inheritance.</p>', unsafe_allow_html=True)
    left, right = st.columns([1, 2])
    with left:
        policy = st.selectbox("Scheduling policy", POLICIES, index=POLICIES.index(st.session_state.policy))
        st.session_state.policy = policy
        if st.button("Run Simulation", type="primary"):
            st.session_state.result = cached_simulation(policy, tuple(st.session_state.specs))
        if st.button("Reset Simulation"):
            st.session_state.result = cached_simulation(policy, tuple(st.session_state.specs))
        if st.button("Load Default Scenario"):
            st.session_state.specs = list(DEFAULT_TASKS)
            st.session_state.result = cached_simulation(policy, tuple(DEFAULT_TASKS))
    with right:
        st.markdown("**Priority convention:** larger numerical values represent higher priority. FCFS selects earliest arrival; priority policies break ties by arrival, then task ID. Each tick reevaluates READY tasks.")
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
    rows = []
    for policy in POLICIES:
        result = cached_simulation(policy, tuple(st.session_state.specs))
        rows.append({"Policy": policy, **result.metrics})
    frame = pd.DataFrame(rows)
    st.dataframe(frame, width="stretch", hide_index=True)
    left, right = st.columns(2)
    with left:
        st.plotly_chart(px.bar(frame, x="Policy", y="average_ready_wait", color="Policy", title="Average READY wait"), width="stretch")
    with right:
        st.plotly_chart(px.bar(frame, x="Policy", y="inversion_duration", color="Policy", title="Priority inversion duration"), width="stretch")
    st.caption("PIP is intended to mitigate lock-caused inversion; other metrics can vary by workload.")
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
