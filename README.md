# A correlation-aware NFL parlay pricing engine 
Rather than predicting football outcomes directly, the system prices
multi-leg parlays by simulating correlated game/player outcomes and comparing the resulting fair price to the sportsbook's
offered price. The product is the pricing disagreement, not a prediction — and specifically the mispricing that comes from
books treating parlay legs as more independent than they really are.

## Web app

A FastAPI backend (`parlay/api/`) exposes the pipeline; a React + Vite frontend
(`frontend/`) is the UI — an **Edge Board** of this week's +EV props and a
**Parlay Builder** that shows the correlation edge on a slip.

Run it (two terminals):

```bash
make run          # backend on http://localhost:8000
make web-install  # once
make web          # frontend on http://localhost:5173  (open this)
```

The backend serves live data when the warehouse + trained models are present
under `parlay/data/`; otherwise it returns **sample data**, flagged in the UI, so
the app runs anywhere. `GET /api/health` reports whether live models loaded.

For a single-process deploy: `make web-build` then `make run` (the API serves
`frontend/dist` at `/`).

