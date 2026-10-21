# Demo day: flow and checklist

## Before the presentation (10 min)
1. Start the server. Run these in a terminal from the project folder:
   `cd "C:\Users\Sneak\Downloads\NC-Archaeologist\nc-archaeologist"`
   `C:\Users\Sneak\ncarch-venv\Scripts\python -m uvicorn ncarch.api:app --port 8765`
2. Open **http://127.0.0.1:8765** in Chrome or Edge. Use `http://`, not https.
3. Click **Same part ×4** and **Results** once so they're loaded, then go back to **Explorer**.
4. Press **F11** for full screen. Zoom the browser to about 90% if the projector is small.
5. Keep `docs/question_bank.md` open on your phone.

## The flow (about 8 minutes): press "▶ Demo tour" and use the → key
The caption at the bottom tells you what to say. Press **N** for more detail.

| # | Screen | What happens | Time |
|---|---|---|---|
| 1 | Explorer: stats | The problem: 600 programs, no CAD, no labels | 30 s |
| 2 | Archive map | Families discovered automatically | 30 s |
| 3 | Families list | Automatic family names | 20 s |
| 4 | 3D viewer | A flange rebuilt from G-code; rotate it with the mouse | 30 s |
| 5 | ▶ Simulation | The cutter removes material, the current G-code line is shown | 45 s |
| 6 | Process sheet | The recovered process plan (CAPP) | 30 s |
| 7 | G-code tab | Hover over a line and read the explanation | 30 s |
| 8 | Similar programs | "Have we made this before?" | 20 s |
| 9 | Same part ×4 | **The key idea**: 4 texts, 1 part | 45 s |
| 10 | Live upload | A new program's processing stages tick through | 40 s |
| 11 | Banner + ★ | Placed in the right family | 15 s |
| 12 | Playground | Change the pocket depth live; offer the professor a turn | 60 s |
| 13 | Results | 0.80 vs 0.07, 94%, 0.999 | 45 s |
| 14 | How it works | "Happy to go into any step. Questions?" | n/a |

## Interactive moments (these make it impressive)
- **Step 4:** hand the mouse to the professor: "Feel free to rotate it."
- **Step 7:** ask them to point at any line, then hover over it.
- **Step 12:** "Would you like to change a value?" Type their number into the editor and press Run.
- **Any time:** "You can upload any G-code file you have."

## If something goes wrong
| Problem | Fix |
|---|---|
| Blank page / no 3D | Check the internet (3D and chart libraries load online). Refresh with Ctrl+Shift+R |
| "Invalid HTTP request" in the terminal | You typed https; use `http://127.0.0.1:8765` |
| "Address already in use" | Another server is running: close it, or use `--port 8766` and open :8766 |
| Tour gets stuck | Press Esc and continue by clicking the pages yourself |
| Total failure | Play your backup screen recording |

## Your 3 one-liners (memorise only these)
1. **Problem:** "Factories have thousands of CNC programs but the CAD is lost: nobody knows what they make."
2. **Idea:** "We simulate each program to rebuild the part, then group programs by what they *make*, not how they're *written*."
3. **Result:** "Part families found with ARI 0.80, against 0.07 for text comparison, on 600 programs the system was never tuned on."
