"""Generate side-by-side Gantt visualizations from the demonstration's CSV output.

Optional dependency: matplotlib. Run: python plot_demo.py
"""
import csv
from pathlib import Path
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / 'demo_output'

def read_csv(path):
    with path.open(newline='') as f:
        return [{k: int(v) for k, v in row.items()} for row in csv.DictReader(f)]

def plot(data, title, filename):
    fig, ax = plt.subplots(figsize=(10, 3.2))
    for job_id in range(5):
        slots = [s for s in data if s['job'] == job_id]
        for s in slots:
            y = s['machine']
            bars = ax.barh(y, s['end']-s['start'], left=s['start'], height=0.5,
                           label=f'Job {job_id}' if s is slots[0] else None)
            ax.text((s['start']+s['end'])/2, y, f"J{s['job']}.{s['operation']}",
                    ha='center', va='center', fontsize=8)
    ax.axvline(8, linestyle='--', linewidth=1.3, label='Failure t=8')
    if 'Recovery' in title:
        ax.barh(0, 8, left=8, height=0.5, alpha=0.18, hatch='///',
                label='M0 downtime (t=8 to 16)')
    ax.set_yticks([0,1,2],['Machine M0','Machine M1','Machine M2'])
    ax.invert_yaxis()
    ax.set_xlim(0,33)
    ax.set_xlabel('Simulated time units')
    ax.set_title(title)
    ax.grid(axis='x',alpha=0.2)
    fig.tight_layout()
    fig.savefig(OUT/filename,dpi=180)
    plt.close(fig)

plot(read_csv(OUT/'baseline.csv'), 'FlexForge: initial feasible shop schedule', 'baseline_gantt.png')
plot(read_csv(OUT/'recovery_edd.csv'), 'FlexForge: Recovery after M0 fails at t=8 (EDD)', 'recovery_gantt.png')