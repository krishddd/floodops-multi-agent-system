# Paper alignment — FloodOps ↔ Nearing et al. (Nature 627, 2024)

Maps the methods in *"Global Prediction of Extreme Floods in Ungauged
Watersheds"* (Nearing et al., **Nature 627**, 559–563, 2024 ·
[doi:10.1038/s41586-024-07145-1](https://doi.org/10.1038/s41586-024-07145-1) ·
the model behind [Google Flood Hub](https://g.co/floodhub)) onto FloodOps'
`FloodPredictAgent`. The paper is in
[`global_flood_prediction_nature_2024.md`](../global_flood_prediction_nature_2024.md).

The guiding rule (CLAUDE.md *Safety rule*): paper-derived reliability **augments**
the forecast — it never gates safety. Phase routing still keys off the
deterministic `max_probability`. Every feature below is computed without the LLM.

---

## Implemented

| Paper concept | Where in paper | FloodOps implementation |
|---|---|---|
| **Ensemble of LSTMs → distribution** (median + uncertainty) | Methods · "ensemble of three… median of the predicted Laplacian" | `FloodPredictAgent` ensemble + `_quantify_uncertainty` (p5–p95 depth band) |
| **Return-period event framing** (1/2/5/10-yr; rarer = harder/more impactful) | Results · *Return Periods*, Figs 1–2 | `ReturnPeriodEvent` + `_classify_return_periods()`; `max_return_period_years` headline. Config: `RETURN_PERIOD_DEPTH_THRESHOLDS_M`, `RETURN_PERIOD_MEMBER_AGREEMENT` |
| **Extended lead time** (skill retained to ~5 days = GloFAS nowcasts → earlier warnings) | Results · *Forecast Lead Time*, Fig 3 | `LeadTimeSkill` + `_estimate_lead_time_skill()`; `skillful_lead_days` warning horizon. Config: `RETURN_PERIOD_BASE_F1`, `LEAD_TIME_SKILL_RETENTION`, `SKILLFUL_F1_THRESHOLD` |
| **Meteorological forcing inputs, no streamflow** (precip/temp/radiation/snowfall; GloFAS is benchmark, not input) | Methods · *Input Data* ("No streamflow data were used as inputs") | `OpenMeteoConnector.get_meteorology()` fetches the paper's variable set; `FloodPredictAgent._forcing_intensity()` drives the ensemble from precip + snowmelt. `get_discharge_ensemble()` relabelled **benchmark reference only** — never an input. |

**Honesty note on the reliability values.** `RETURN_PERIOD_BASE_F1` and
`LEAD_TIME_SKILL_RETENTION` are **illustrative reference curves** distilled from
the paper's published findings (F1 by return period falls in ~0.15–0.55; skill
holds through day 5 then degrades), **not** a live skill measurement. A real
deployment reads empirical per-gauge F1 from a hindcast archive. The code and
config comments say so explicitly so nobody mistakes them for measured skill.

---

## Not yet wired (v3 candidates)

| Paper concept | Section | Why deferred |
|---|---|---|
| **Area-averaging over basin polygons** + full ECMWF IFS/ERA5/IMERG source set | Methods · *Input Data* | Forcing is now meteorological (precip/temp/radiation/snowfall) via Open-Meteo, but sampled at the **basin centroid**, not area-weighted over the upstream polygon; and NOAA CPC / NASA IMERG aren't wired. |
| **Upstream snowpack / glacial melt** | — | `_forcing_intensity` only credits snowmelt when there is snow **in the point forecast window**; it misses melt of existing upstream snowpack/glaciers (the GLOF driver), which needs basin snow-state we can't get keyless. |
| **Predicted reliability from catchment attributes** (drainage area, PET, AET, elevation → where the model is skillful) | Results · *Predictability of Forecast Reliability*, Figs 5–6, Ext. Data Fig 3 | Needs HydroATLAS attributes; the GDAL attribute connectors are still mocks (`requirements-geo.txt`). |
| **HydroBASINS level-12 topology** (1.03M watersheds) | Fig 6 | `WATERSHED_TOPOLOGY` is a hand-coded 5-edge Bagmati demo (`config.py`). |
| **Hydrograph metrics** (NSE / KGE / log-NSE …) | Methods · *Metrics*, Ext. Data Table 1 | Evaluation harness, not a live forecast field. |
| **Bulletin 17B per-gauge return-period thresholds** | Methods · *Metrics* | Current depth thresholds are coarse demo values; real thresholds come from a flood-frequency fit on the observed record. |

---

## Reproduce / go deeper

- Research model (LSTM encoder–decoder): [NeuralHydrology](https://neuralhydrology.github.io)
- Trained models + reanalysis/reforecast data: [Zenodo 10397664](https://doi.org/10.5281/zenodo.10397664)
- Figure/analysis code: [google-research-datasets/global_streamflow_model_paper](https://github.com/google-research-datasets/global_streamflow_model_paper)
- Contribute streamflow data: [Caravan](https://github.com/kratzert/Caravan)
