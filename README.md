# SurgiQueue - Intelligent Hospital Resource Coordination System

## Setup
Install Python 3.10+, then run these commands from the project folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Verify the code

```powershell
pytest -q
```

The suite covers scheduling order, arrivals, mutex ownership, blocking and
unblocking, priority inversion, PIP, aging, metrics, and deterministic runs.

## Launch the dashboard

```powershell
python -m streamlit run app.py
```

Open http://localhost:8501.

## Navigation

The sidebar contains Overview, Patient Queue, Operating Rooms, Medical Teams,
Equipment, Surgery Schedule, OS Scheduler, Analytics, and About the Project.
Hospital pages use fictional workflow records. The OS Scheduler is the primary
technical contribution and uses software tasks competing for mutex `R1`.

The default scenario demonstrates P3 holding `R1`, P1 becoming blocked, and P2
running under strict priority. Select Priority + PIP + Aging to see the owner
inherit P1's priority and release the lock sooner. Analytics compares all three
policies and event logs can be downloaded as CSV.

## Simulation rules

Higher effective priority wins, followed by earlier arrival and task ID. Only
READY tasks are candidates. FCFS uses arrival order. PIP changes the effective
priority of a mutex owner; aging raises the score of eligible READY tasks and
never changes blocked time. All time advances in deterministic logical ticks.
The healthcare context is separate from clinical triage, treatment, and surgery
allocation decisions.

## Troubleshooting
- `ModuleNotFoundError`: venv not active, or run `pip install -r requirements.txt` again.
- `streamlit` not recognised: use `python -m streamlit run app.py`.
- Port busy: `streamlit run app.py --server.port 8502`.
