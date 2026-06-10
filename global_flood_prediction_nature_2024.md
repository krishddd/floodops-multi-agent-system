# Global Prediction of Extreme Floods in Ungauged Watersheds

**Journal:** Nature | Vol 627 | 21 March 2024 | pp. 559–563  
**DOI:** https://doi.org/10.1038/s41586-024-07145-1  
**Received:** 29 July 2023 | **Accepted:** 31 January 2024 | **Published online:** 20 March 2024  
**Access:** Open Access (CC BY 4.0)

---

## Authors

Grey Nearing¹ ✉, Deborah Cohen¹, Vusumuzi Dube¹, Martin Gauch¹, Oren Gilon¹, Shaun Harrigan², Avinatan Hassidim¹, Daniel Klotz³, Frederik Kratzert¹, Asher Metzger¹, Sella Nevo⁴, Florian Pappenberger², Christel Prudhomme², Guy Shalev¹, Shlomo Shenzis¹, Tadele Yednkachw Tekalign¹, Dana Weitzner¹ & Yossi Matias¹

**Affiliations:**  
¹ Google, https://research.google/  
² European Centre for Medium-Range Weather Forecasts, Reading, UK  
³ Helmholtz Centre for Environmental Research – UFZ, Leipzig, Germany  
⁴ RAND Corporation, Los Angeles, CA, USA  

✉ Correspondence: nearing@google.com

---

## Abstract

Floods are one of the most common natural disasters, with a disproportionate impact in developing countries that often lack dense streamflow gauge networks. Accurate and timely warnings are critical for mitigating flood risks, but hydrological simulation models typically must be calibrated to long data records in each watershed. Here we show that artificial intelligence-based forecasting achieves reliability in predicting extreme riverine events in ungauged watersheds at up to a five-day lead time that is similar to or better than the reliability of nowcasts (zero-day lead time) from a current state-of-the-art global modelling system (the Copernicus Emergency Management Service Global Flood Awareness System). In addition, we achieve accuracies over five-year return period events that are similar to or better than current accuracies over one-year return period events. This means that artificial intelligence can provide flood warnings earlier and over larger and more impactful events in ungauged basins. The model developed here was incorporated into an operational early warning system that produces publicly available (free and open) forecasts in real time in over 80 countries. This work highlights a need for increasing the availability of hydrological data to continue to improve global access to reliable flood warnings.

---

## Introduction

Floods are the most common type of natural disaster and the rate of flood-related disasters has more than doubled since 2000. This increase in flood-related disasters is driven by an accelerating hydrological cycle caused by anthropogenic climate change. Early warning systems are an effective way to mitigate flood risks, reducing flood-related fatalities by up to 43% and economic costs by 35–50%. Populations in low- and middle-income countries make up almost 90% of the 1.8 billion people that are vulnerable to flood risks. The World Bank has estimated that upgrading flood early warning systems in developing countries to the standards of developed countries would save an average of 23,000 lives per year.

In this paper, we evaluate the extent to which artificial intelligence (AI) trained on open, public datasets can be used to improve global access to forecasts of extreme events in global rivers. On the basis of the model and experiments described in this paper, we developed an operational system that produces short-term (7-day) flood forecasts in over 80 countries. These forecasts are available in real time without barriers to access such as monetary charge or website registration (https://g.co/floodhub).

A major challenge for riverine forecasting is that hydrological prediction models must be calibrated to individual watersheds using long data records. Watersheds that lack stream gauges to supply data for calibration are called ungauged basins, and the problem of 'prediction in ungauged basins' (PUB) was the decadal problem of the International Association of Hydrological Sciences (IAHS) from 2003 to 2012. At the end of the PUB decade, the IAHS reported that little progress had been made against the problem, stating that "much of the success so far has been in gauged rather than in ungauged basins, which has negative effects in particular for developing countries."

Only a few per cent of the world's watersheds are gauged, and stream gauges are not distributed uniformly across the world. There is a strong correlation between national gross domestic product and the total publicly available streamflow observation data record in a given country, which means that high-quality forecasts are especially challenging in areas that are most vulnerable to the human impacts of flooding.

In previous work, we showed that machine learning can be used to develop hydrological simulation models that are transferable to ungauged basins. Here we develop that into a global-scale forecasting system with the goal of understanding scalability and reliability. In this paper, we address whether, given the publicly available global streamflow data record, it is possible to provide accurate river forecasts across large scales, especially of extreme events, and how this compares with the current state of the art.

The current state of the art for real-time, global-scale hydrological prediction is the Global Flood Awareness System (GloFAS). GloFAS is the global flood forecasting system of Copernicus Emergency Management Service (CEMS), delivered under the responsibility of the European Commission's Joint Research Centre and operated by the European Centre for Medium-Range Weather Forecasts (ECMWF) in its role of CEMS Hydrological Forecast Centre – Computation. We use GloFAS version 4, which is the current operational version that went live in July 2023. Other forecasting systems exist for different parts of the world, and many countries have national agencies responsible for producing early warnings. Given the severity of impacts that floods have on communities around the world, we consider it critical that forecasting agencies evaluate and benchmark their predictions, warnings and approaches, and an important first step towards this goal is archiving historical forecasts.

---

## Results

### AI Improves Forecast Reliability

The AI model developed for this study uses long short-term memory (LSTM) networks to predict daily streamflow through a 7-day forecast horizon. The model is described in detail in Methods, and a version of the model suitable for research is implemented in the open-source NeuralHydrology repository. Input, target and evaluation data are described in Methods.

This AI forecast model was trained and tested out-of-sample using random k-fold cross-validation across 5,680 streamflow gauges. Other types of cross-validation experiment are reported in Methods (that is, by withholding all gauges in terminal watersheds, entire climate zones or entire continents). In addition, all metrics reported for the AI model were calculated with streamflow gauge data from time periods not present in training (in addition to stream gauges that were not present in training), meaning that cross-validation splits were out-of-sample across time and location. By contrast, metrics for GloFAS were calculated over a combination of gauged and ungauged locations, and over a combination of calibration and validation time periods. This means that the comparison favours the GloFAS benchmark. This is necessary because calibrating GloFAS is computationally expensive to the extent that it is not feasible to re-calibrate over cross-validation splits.

Our objective is to understand the reliability of forecasts of extreme events, so we report precision, recall and F1 scores (F1 scores are the harmonic mean of precision and recall) over different return period events. Other standard hydrological metrics are reported in Methods. Statistical tests are described in Methods.

Figure 1 shows the global distribution of F1 score differences for 2-year return period events at a 0-day lead time over the period 1984–2021 (N = 3,360). Lead time is expressed as the number of days from the time of prediction, such that a 0-day lead time means that streamflow predictions are for the current day (nowcasts). The AI model improved over (was at least equivalent to) GloFAS version 4 in:

- **1-year return period events** (N = 3,638, P = 6 × 10⁻⁸⁷, Cohen's d = 0.22): 64% improved, 65% at least equivalent
- **2-year return period events** (N = 3,673, P < 3 × 10⁻¹⁸¹, d = 0.41): 70% improved, 73% at least equivalent
- **5-year return period events** (N = 3,360, P = 8 × 10⁻¹³⁰, d = 0.42): 60% improved, 73% at least equivalent
- **10-year return period events** (N = 2,920, P < 1 × 10⁻⁶⁶, d = 0.33): 49% improved, 76% at least equivalent

> **Figure 1.** Differences between nowcast (0-day lead time) F1 scores for 2-year return period events between our AI model and GloFAS over the period 1984–2021. The AI model improves over GloFAS in 70% of gauges (N = 3,673).

### Return Periods

More extreme hydrological events (that is, events with larger return periods) are both more important and (when using classical hydrology models) typically more difficult to predict. A common concern about using AI or other types of data-driven approach is that reliability might degrade over events that are rare in the training data. There is prior evidence that this concern might not be valid for streamflow modelling.

Figure 2 shows the distributions over precision and recall for different return period events. The AI model has higher precision and recall scores for all return periods (N > 3,000, P < 1 × 10⁻⁵), with effect sizes ranging from d = 0.15 (1-year precision scores) to d = 0.46 (2-year recall scores). Differences between precision scores from the AI model over 5-year return period events and from GloFAS over 1-year return period events are not significant at α = 1% (N = 3,465, P = 0.02, d = −0.01), and recall scores from the AI model for 5-year events are better than GloFAS recall scores for 1-year events (N = 3,586, P = 1 × 10⁻¹⁸, d = 0.20).

> **Figure 2.** Distributions over nowcast (0-day lead time) precision and recall as a function of return period. The AI model is more reliable, on average, over all return periods. The AI model has precision over 5-year return period events that is not statistically different to GloFAS over 1-year return period events, and recall that is better than GloFAS over 1-year return period events.

### Forecast Lead Time

Figure 3 shows F1 scores over lead times through the 7-day forecast horizon for return periods between 1 year and 10 years. Compared with GloFAS nowcasts (0-day lead time), AI forecasts have either better or not statistically different reliability (F1 scores) up to a 5-day lead time for:

- **1-year events:** AI is significantly better (N = 2,415, P = 6 × 10⁻⁶, d = 0.08)
- **2-year events:** No statistical difference (N = 2,162, P = 0.98, d = 2 × 10⁻⁴)
- **5-year events:** No statistical difference (N = 1,298, P = 0.69, d = 0.025)

> **Figure 3.** Distributions over F1 scores at all evaluation gauges as a function of lead time for different return periods. The AI model has F1 scores over 1-year, 2-year, 5-year and 10-year return period events at up to 5-day lead times that are either statistically better than or not statistically different to GloFAS over the same events at 0-day lead time.

### Continents

Both models show differences in reliability in different areas of the world. Over 5-year return period events:

- **GloFAS:** 54% difference between mean F1 scores in the lowest-scoring continent (South America, F1 = 0.15) and the highest-scoring continent (Europe, F1 = 0.32)
- **AI model:** 54% difference between mean F1 scores in the lowest-scoring continent (South America, F1 = 0.21) and the highest-scoring continent (Southwest Pacific, F1 = 0.46), which is due mostly to a large increase in skill in the Southwest Pacific relative to GloFAS (d = 0.68)

Figure 4 shows the distributions of F1 scores over continents and return periods. The AI model has higher scores in all continents and return periods (P < 1 × 10⁻², 0.10 < d < 0.68) with three exceptions where there is no statistical difference:

- Africa over 1-year return period events (P = 0.07, d = 0.03)
- Asia over 5-year return period events (P = 0.04, d = 0.12)
- Asia over 10-year return period events (P = 0.18, d = 0.12)

> **Figure 4.** F1 score distributions over different continents and return periods. The AI model has higher scores in all continents over 1-year, 2-year, 5-year and 10-year return period events with three exceptions where there is no statistical difference: Africa over 1-year return period events and Asia over 5-year and 10-year return period events. Both models have large location-based differences between reliability that could be addressed by increasing global access to open hydrological data.

### Predictability of Forecast Reliability

A challenge to forecasting in ungauged basins is that there is often no way to evaluate reliability in locations without ground-truth data. A desirable quality of a model is that forecast skill should be predictable from other observable variables, such as mapped or remotely sensed geographical and/or geophysical data. In addition, although AI-based forecasting offers better reliability in most places, this is not the case everywhere. It would be beneficial to be able to predict where different models can be expected to be more or less reliable.

We have found that it is difficult to use catchment attributes (geographical, geophysical data) to predict where one model performs better than another. Extended Data Fig. 2 shows a confusion matrix from a random forest classifier trained on a subset of HydroATLAS attributes that predicts whether the AI model or GloFAS performs better (or similar) in each individual watershed. The classifier was trained with stratified k-fold cross-validation and balanced sampling, and usually predicts that the AI model is better (including in 70% of cases where GloFAS is actually better). This indicates that it is difficult to find systematic patterns about where each model is preferable, based on available catchment attributes.

However, it is possible to predict, with some skill, where an individual model will perform well versus poorly. Figure 5 shows confusion matrices from random forest classifiers that predict whether F1 scores for out-of-sample gauges (effectively ungauged locations) will be above or below the mean over all evaluation gauges. Both models (the AI model and GloFAS) have similar overall predictability (71% micro-averaged precision and recall for GloFAS and 73% for the AI model).

Feature importances from these reliability classifiers are shown in Extended Data Fig. 3. The most important features are:

- **AI model:** drainage area, mean annual potential evapotranspiration (PET), mean annual actual evapotranspiration (AET), and elevation
- **GloFAS:** PET and AET

Correlations between attributes and reliability scores are generally low, indicating a high degree of nonlinearity and/or parameter interaction.

AET and PET are (inverse) indicators of aridity, and hydrology models usually perform better in humid basins because peaky hydrographs that occur in arid watersheds are difficult to simulate. This effect is present for both models. The AI model is more correlated with basin size (drainage area) and generally performs better in smaller basins. This indicates a way that machine-learning-based streamflow modelling might be improved, for example, by focusing training or fine-tuning on larger basins, or by implementing an explicit routing or graph model to allow for direct modelling of subwatersheds or smaller hydrological response units.

A global map of the predicted skill from a regression (rather than classifier) version of this random forest skill predictor is shown in Fig. 6 for 1.03 million level-12 HydroBASINS watersheds. This gives some indication about where a global version of the ungauged AI forecast model is expected to perform well.

> **Figure 5.** Testing the ability to predict whether a given model will perform above or below average at any given location. Confusion matrices of out-of-sample predictions about whether F1 scores from GloFAS and the AI model at each gauge are above or below the mean F1 score from the same model over all gauges.

> **Figure 6.** Global predicted skill. This map shows predictions of 2-year return period F1 scores over 1.03 million HydroBASINS level-12 watersheds for the AI forecast model.

---

## Conclusion and Discussion

Although hydrological modelling is a relatively mature area of study, areas of the world that are most vulnerable to flood risks often lack reliable forecasts and early warning systems. Using AI and open datasets, we are able to significantly improve the expected precision, recall and lead time of short-term (0–7 days) forecasts of extreme riverine events. We extended, on average, the reliability of currently available global nowcasts (lead time 0) to a lead time of 5 days, and we were able to use AI-based forecasting to improve the skill of forecasts in Africa to be similar to what are currently available in Europe.

Apart from producing accurate forecasts, another aspect of the challenge of providing actionable flood warnings is dissemination of those warnings to individuals and organizations in a timely manner. We support the latter by releasing forecasts publicly in real time, without cost or barriers to access. We provide open-access real-time forecasts to support notifications — for example, through the Common Alerting Protocol and push alerts to personal smartphones, and through an open online portal at https://g.co/floodhub. All of the reanalysis and reforecasts used for this study are included in an open-source repository, and a research version of the machine-learning model used for this study is available as part of the open-source NeuralHydrology repository on GitHub.

There is still a lot of room to improve global flood predictions and early warning systems. Doing so is critical for the well-being of millions of people worldwide whose lives (and property) could benefit from timely, actionable flood warnings. We believe that the best way to improve flood forecasts from both data-driven and conceptual modelling approaches is to increase access to data. Hydrological data are required for training or calibrating accurate hydrology models, and for updating these models in real time (for example, through data assimilation). We encourage researchers and organizations with access to streamflow data to contribute to the open-source Caravan project at https://github.com/kratzert/Caravan.

---

## Methods

### AI Model

The AI streamflow forecasting model reported in this paper extends previous work, which developed hydrological nowcast models using LSTM networks that simulate sequences of streamflow data from sequences of meteorological input data. Building on that, we developed a forecast model that uses an encoder–decoder model with one LSTM running over a historical sequence of meteorological (and geophysical) input data (the encoder LSTM) and another, separate, LSTM that runs over the 7-day forecast horizon with inputs from meteorological forecasts (the decoder LSTM).

**Key architectural parameters:**
- Hindcast sequence length: 365 days
- Hidden size: 256 cell states for both encoder and decoder LSTMs
- Transfer networks: linear cell-state transfer + nonlinear hidden-state transfer (fully connected layer with hyperbolic tangent activation)
- Training: 50,000 minibatches, batch size of 256
- All inputs standardized (subtract mean, divide by standard deviation of training data)

The model predicts, at each time step, parameters of a single asymmetric Laplacian distribution over area-normalized streamflow discharge. The loss function is the joint negative log-likelihood of that heteroscedastic density function. Results were calculated over a hydrograph resulting from averaging the predicted hydrographs from an ensemble of three separately trained encoder–decoder LSTMs. The hydrograph from each of these LSTMs is taken as the median (50th percentile) flow value from the predicted Laplacian distribution at each time step and forecast lead time.

**Training time:** A few hours on a single NVIDIA-V100 GPU (approximately 10 hours for the full global model with 50 validation steps every 1,000 batches).

### Input Data

The full dataset includes model inputs and streamflow targets for a total of 152,259 years from 5,680 watersheds. Total dataset size: 60 GB.

Input data sources:

- **ECMWF IFS HRES:** Daily-aggregated single-level forecasts. Variables: total precipitation (TP), 2-m temperature (T2M), surface net solar radiation (SSR), surface net thermal radiation (STR), snowfall (SF), surface pressure (SP)
- **ECMWF ERA5-Land reanalysis:** Same six variables as above
- **NOAA CPC Global Unified Gauge-Based Analysis of Daily Precipitation**
- **NASA IMERG Early Run:** Integrated Multi-satellite Retrievals for GPM precipitation estimates
- **HydroATLAS database:** Geological, geophysical and anthropogenic basin attributes

All input data were area-weighted averaged over basin polygons over the total upstream area of each gauge or prediction point. The total upstream area for the 5,680 evaluation gauges ranged from 2.1 km² to 4,690,998 km².

No streamflow data were used as inputs to the AI model because (1) real-time data are not available everywhere, especially in ungauged locations, and (2) the benchmark (GloFAS) does not use autoregressive inputs.

### Target and Evaluation Data

Training and test targets came from the Global Runoff Data Center (GRDC). Watersheds were removed from the full public GRDC dataset where drainage area reported by GRDC differed by more than 20% from drainage area calculated using watershed polygons from the HydroBASINS repository. This left 5,680 gauges.

### Experiments

Cross-validation protocol: data from 5,680 gauges split in two ways:
1. **Time splits:** No training data from any gauge used within 1 year (the LSTM encoder sequence length) of any test data from any gauge
2. **Spatial splits:** Randomized (without replacement) k-fold cross-validation with k = 10

Additional cross-validation experiments:
- Cross-validation splits across continents (k = 6)
- Cross-validation splits across climate zones (k = 13)
- Cross-validation splits across groups of hydrologically separated watersheds (k = 8)

### GloFAS

GloFAS inputs are similar to the AI model input data, with key differences:
- GloFAS uses ERA5 (not ERA5-Land) as forcing data
- GloFAS does not use ECMWF IFS as model input
- GloFAS does not use NOAA CPC or NASA IMERG data as direct inputs

GloFAS predictions are provided on a 3-arcmin grid (approximately 5-km horizontal resolution). All GRDC stations with drainage area smaller than 500 km² were discarded to avoid large discrepancies between GRDC and GloFAS drainage networks. A total of 4,090 GRDC stations were geolocated on the GloFAS grid.

Unlike the AI model, GloFAS was not tested completely out-of-sample. GloFAS predictions came from a combination of gauged and ungauged catchments, and a combination of calibration and validation time periods. **This means that the comparison with the AI model favours GloFAS.** Additionally, long-term archive of GloFAS version 4 reforecasts did not span the full year at time of analysis, meaning it is only possible to benchmark GloFAS at a 0-day lead time.

### Metrics

Primary metrics: **precision**, **recall**, and **F1 score** (harmonic mean of precision and recall) over predictions of events defined by return periods.

Return periods were calculated separately for each of the 5,680 gauges on both modelled and observed time series using the methodology described by the US Geological Survey Bulletin 17b. A model was considered to have correctly predicted an event with a given return period if the modelled hydrograph and the observed hydrograph both crossed their respective return period threshold flow values **within two days of each other**.

All statistical significance values were assessed using **two-sided Wilcoxon (paired) signed-rank tests**. Effect sizes are reported as **Cohen's d**, with the convention that the AI model having better mean predictions results in a positive effect size.

Standard hydrological metrics also reported (Extended Data):

| Metric | Description |
|--------|-------------|
| NSE | Nash–Sutcliffe efficiency |
| log-NSE | Nash–Sutcliffe efficiency in logarithmic space |
| Alpha-NSE | Ratio of standard deviations of observed and simulated flow |
| Beta-NSE | Bias scaled by standard deviation of observations |
| KGE | Kling–Gupta efficiency |
| log-KGE | Kling–Gupta efficiency in logarithmic space |
| Beta-KGE | Ratio of mean simulated and mean observed flow |

### Data Availability

Reanalysis (1984–2021) and reforecast (2014–2021) data produced by the AI model for this study, as well as corresponding GloFAS benchmark data, are available at: https://doi.org/10.5281/zenodo.10397664

### Code Availability

Fully functional trained models: https://doi.org/10.5281/zenodo.10397664

NeuralHydrology framework (research-grade models): https://neuralhydrology.github.io

Code for reproducing figures and analyses: https://github.com/google-research-datasets/global_streamflow_model_paper

Input data sources:
- NASA IMERG: https://gpm.nasa.gov/data
- ECMWF HRES: https://www.ecmwf.int/en/forecasts/datasets/set-i
- ECMWF ERA5-Land: https://cds.climate.copernicus.eu/cdsapp#!/dataset/reanalysis-era5-land
- NOAA CPC: https://psl.noaa.gov/data/gridded/data.cpc.globalprecip.html

---

## Extended Data

### Extended Data Figure 1 — Streamflow Data Availability Correlates with National GDP

There is a log-log correlation (r = 0.611; N = 117) between national Gross Domestic Product (GDP) and the total number of years' worth of daily streamflow data available in a country from the Global Runoff Data Center. GDP data sourced from The World Bank.

### Extended Data Figure 2 — Confusion Matrix: Which Model Performs Better?

Confusion matrix of a classifier that predicts whether the AI model or GloFAS had a higher (or similar) F1 score in a given watershed based on geophysical catchment attributes (N = 3,360). The task is generally not possible given available catchment attribute data. The classifier usually predicts that the AI model is better (including in 70% of cases where GloFAS is actually better).

| | AI Model | Tied | GloFAS |
|--|---------|------|--------|
| **True: AI Model** | 0.88 | 0.037 | 0.084 |
| **True: Tied** | 0.64 | 0.22 | 0.14 |
| **True: GloFAS** | 0.68 | 0.07 | 0.25 |

### Extended Data Figure 3 — Feature Importance Rankings of Score Classifiers

Full feature importance rankings for classifiers predicting whether GloFAS (panel a) or the AI model (panel b) performs better or worse than average in any given gauge location.

**Top features for GloFAS classifier:** PET, AET, Soil Erosion, Slope, Elevation, Air Temperature, Precipitation, Forest Cover Area, Drain Area, Population Density...

**Top features for AI model classifier:** Drain Area, PET, AET, Elevation, Precipitation, Lake Volume, Forest Cover Area, Slope, Soil Erosion, Air Temperature, River Volume, GDP...

### Extended Data Figure 4 — LSTM Forecast Model Architecture

Architecture of the LSTM-based encoder–decoder forecast model used operationally to support Google Flood Hub (https://g.co/floodhub).

Components:
- **Hindcast LSTM** — processes 365-day historical meteorological sequence
- **Forecast LSTM** — processes 7-day forecast horizon with IFS forecast inputs
- **Static feature embedding** — encodes basin attributes; output used as LSTM input
- **Hindcast Head** and **Forecast Head** — output layers
- **Embedding Network** — processes static features
- **Hidden state transfer network** — nonlinear transfer between encoder and decoder
- **Cell state transfer network** — linear transfer between encoder and decoder
- **Model output** — CMAL (Countable Mixture of Asymmetric Laplacians) parameters

### Extended Data Figure 5 — Model Input and Training Data Timeline

Timeline showing availability of each data source (1980 to Real Time):

- **GRDC Streamflow Target Data:** ~1980 onwards
- **ERA5-Land:** ~1980 onwards
- **CPC Global Unified Gauge-Based Analysis of Daily Precipitation:** ~1980 onwards
- **IMERG Precipitation:** ~2000 onwards
- **ECMWF HRES Forecasts:** ~2012 onwards (real-time)

### Extended Data Figure 6 — Gauge Locations

Location of gauges used for:
- Training the AI model (N = 5,860)
- Calibrating GloFAS (N = 1,144)
- Calculating evaluation metrics reported in this paper (N = 4,089)

The AI model is a single model trained on data from all gauges simultaneously, while GloFAS was calibrated separately per-location following a top-down approach from head-catchments to downstream catchments. All AI model evaluation was done out-of-sample in both location and time.

### Extended Data Figure 7 — Cross-Validation Split Gauge Locations

Locations of gauges in each cross-validation split:
- **(a) Random splits** — results reported in main text
- **(b) Continent splits** — all basins in a particular continent in one group (k = 6)
- **(c) Climate zone splits** — all basins in each of 13 climate zones in one group (k = 13)
- **(d) Hydrologically-separated splits** — groups gauges in hydrologically-separated terminal basins (k = 8)

### Extended Data Figures 8 & 9 — Hydrograph Metrics

Standard hydrograph metrics for the AI model and GloFAS evaluated over:
- **Extended Data Fig. 8:** All 4,089 evaluation gauges
- **Extended Data Fig. 9:** The 1,144 gauges where GloFAS is calibrated

Key finding: The ungauged AI model performs about as well in ungauged basins as GloFAS performs in gauged basins when evaluated against KGE (the metric GloFAS is calibrated on), and better than GloFAS in gauged basins on NSE metrics. GloFAS has better overall variance (Alpha-NSE) than the ungauged AI model in calibrated locations, indicating a potential area for improvement.

### Extended Data Table 1 — Standard Hydrograph Evaluation Metrics

| Metric | Description | Reference |
|--------|-------------|-----------|
| NSE | Nash–Sutcliffe efficiency | Eq. 3 in Nash & Sutcliffe (1970) |
| log-NSE | Nash–Sutcliffe efficiency in logarithmic space | — |
| Alpha-NSE | Ratio of standard deviations of observed and simulated flow | Eq. 4 in Gupta et al. (2009) |
| Beta-NSE | Bias scaled by standard deviation of observations | Eq. 4 in Gupta et al. (2009) |
| KGE | Kling–Gupta efficiency | Eq. 9 in Gupta et al. (2009) |
| log-KGE | Kling–Gupta efficiency in logarithmic space | — |
| Beta-KGE | Ratio of mean simulated and mean observed flow | Eq. 10 in Gupta et al. (2009) |

---

## References

1. Rentschler, J., Salhab, M. & Jafino, B. A. Flood exposure and poverty in 188 countries. *Nat. Commun.* **13**, 3527 (2022).
2. Hallegatte, S. *A Cost Effective Solution to Reduce Disaster Losses in Developing Countries: Hydro-meteorological Services, Early Warning, and Evacuation* Policy Research Working Paper 6058 (World Bank, 2012).
3. *The Human Cost of Natural Disasters: A Global Perspective* (United Nations International Strategy for Disaster Reduction, 2015).
4. *2021 State of Climate Services* WMO-No. 1278 (World Meteorological Organization, 2021).
5. Milly, P., Christopher, D., Wetherald, R. T., Dunne, K. A. & Delworth, T. L. Increasing risk of great floods in a changing climate. *Nature* **415**, 514–517 (2002).
6. Tabari, H. Climate change impact on flood and extreme precipitation increases with water availability. *Sci. Rep.* **10**, 13768 (2020).
7. *Global Report on Drowning: Preventing A Leading Killer* (World Health Organization, 2014).
8. *The Global Climate 2001–2010: A Decade of Climate Extremes* Technical Report (World Health Organization, 2013).
9. Pilon, P. J. *Guidelines for Reducing Flood Losses* Technical Report (United Nations International Strategy for Disaster Reduction, 2002).
10. Rogers, D. & Tsirkunov, V. *Costs and Benefits of Early Warning Systems: Global Assessment Report on Disaster Risk Reduction* (The World Bank, 2010).
11. Razavi, S. & Tolson, B. A. An efficient framework for hydrologic model calibration on long data periods. *Water Resour. Res.* **49**, 8418–8431 (2013).
12. Li, Chuan-zhe et al. Effect of calibration data series length on performance and optimal parameters of hydrological model. *Water Sci. Eng.* **3**, 378–393 (2010).
13. Sivapalan, M. et al. IAHS decade on predictions in ungauged basins (PUB), 2003–2012: shaping an exciting future for the hydrological sciences. *Hydrol. Sci. J.* **48**, 857–880 (2003).
14. Hrachowitz, M. et al. A decade of predictions in ungauged basins (PUB)—a review. *Hydrol. Sci. J.* **58**, 1198–1255 (2013).
15. Kratzert, F. et al. Toward improved predictions in ungauged basins: exploiting the power of machine learning. *Water Resour. Res.* **55**, 11344–11354 (2019).
16. Alfieri, L. et al. GloFAS—global ensemble streamflow forecasting and flood early warning. *Hydrol. Earth Syst. Sci.* **17**, 1161–1175 (2013).
17. Harrigan, S., Zsoter, E., Cloke, H., Salamon, P. & Prudhomme, C. Daily ensemble river discharge reforecasts and real-time forecasts from the operational global flood awareness system. *Hydrol. Earth Syst. Sci.* **27**, 1–19 (2023).
18. Arheimer, B. et al. Global catchment modelling using world-wide HYPE (WWH), open data, and stepwise parameter estimation. *Hydrol. Earth Syst. Sci.* **24**, 535–559 (2020).
19. Souffront Alcantara, M. A. et al. Hydrologic modeling as a service (HMaaS): a new approach to address hydroinformatic challenges in developing countries. *Front. Environ. Sci.* **7**, 158 (2019).
20. Sheffield, J. et al. A drought monitoring and forecasting system for sub-sahara African water resources and food security. *Bull. Am. Meteorol. Soc.* **95**, 861–882 (2014).
21. Hochreiter, S. & Schmidhuber, J. Long short-term memory. *Neural Comput.* **9**, 1735–1780 (1997).
22. Kratzert, F., Gauch, M., Nearing, G. S. & Klotz, D. NeuralHydrology—a Python library for deep learning research in hydrology. *J. Open Source Softw.* **7**, 4050 (2022).
23. Sellars, S. L. 'Grand challenges' in big data and the Earth sciences. *Bull. Am. Meteorol. Soc.* **99**, ES95–ES98 (2018).
24. Todini, E. Hydrological catchment modelling: past, present and future. *Hydrol. Earth Syst. Sci.* **11**, 468–482 (2007).
25. Herath, H. M. V. V., Chadalawada, J. & Babovic, V. Hydrologically informed machine learning for rainfall–runoff modelling: towards distributed modelling. *Hydrol. Earth Syst. Sci.* **25**, 4373–4401 (2021).
26. Reichstein, M. et al. Deep learning and process understanding for data-driven Earth system science. *Nature* **566**, 195–204 (2019).
27. Frame, J. M. et al. Deep learning rainfall–runoff predictions of extreme events. *Hydrol. Earth Syst. Sci.* **26**, 3377–3392 (2022).
28. Linke, S. et al. Global hydro-environmental sub-basin and river reach characteristics at high spatial resolution. *Sci. Data* **6**, 283 (2019).
29. Kratzert, F. et al. Large-scale river network modeling using graph neural networks. In *European Geosciences Union General Assembly Conference Abstracts* EGU21–13375 (EGU General Assembly, 2021).
30. Lehner, B. & Grill, G. Global river hydrography and network routing: baseline data and new approaches to study the world's large river systems. *Hydrol. Proces.* **27**, 2171–2186 (2013).
31. Nearing, G. S. et al. Data assimilation and autoregression for using near-real-time streamflow observations in long short-term memory networks. *Hydrol. Earth Syst. Sci.* **26**, 5493–5513 (2022).
32. Kratzert, F. et al. Caravan—a global community dataset for large-sample hydrology. *Sci. Data* **10**, 61 (2023).
33. Grimaldi, S. et al. River discharge and related historical data from the Global Flood Awareness System. *Climate Data Store* https://doi.org/10.24381/cds.a4fdd6b9 (2023).
34. Jordahl, K. et al. geopandas/geopandas: v0.8.1 https://zenodo.org/records/3946761 (2020).
35. Kratzert, F. et al. Towards learning universal, regional, and local hydrological behaviors via machine learning applied to large-sample datasets. *Hydrol. Earth Syst. Sci.* **23**, 5089–5110 (2019).
36. Klotz, D. et al. Uncertainty estimation with deep learning for rainfall–runoff modeling. *Hydrol. Earth Syst. Sci.* **26**, 1673–1693 (2022).
37. *Global Composite Runoff Fields* (CSRC-UNH and GRDC, 2002).
38. Grimaldi, S. GloFAS v4 calibration methodology and parameters. ECMWF https://confluence.ecmwf.int/display/CEMS/GloFAS+v4+calibration+methodology+and+parameters (2023).
39. Interagency Advisory Committee on Water Data. *Guidelines for Determining Flood Flow Frequency Bulletin #17B of the Hydrology Subcommittee* (US Department of the Interior Geological Survey, 1982).
40. Sullivan, G. M. & Feinn, R. Using effect size—or why the P value is not enough. *J. Grad. Med. Educ.* **4**, 279–282 (2012).
41. Gauch, M. et al. In defense of metrics: metrics sufficiently encode typical human preferences regarding hydrological model performance. *Water Resour. Res.* **59**, e2022WR033918 (2023).
42. *Forecast Verification Methods Across Time and Space Scales* (World Weather Research Programme, 2016).
43. Nash, J. E. & Sutcliffe, J. V. River flow forecasting through conceptual models part I—a discussion of principles. *J. Hydrol.* **10**, 282–290 (1970).
44. Gupta, H. V., Kling, H., Yilmaz, K. K. & Martinez, G. F. Decomposition of the mean squared error and NSE performance criteria: implications for improving hydrological modelling. *J. Hydrol.* **377**, 80–91 (2009).
45. Nearing, G. AI increases global access to reliable flood forecasts. *Zenodo* https://doi.org/10.5281/zenodo.10397664 (2023).
46. GDP Current US$. *World Bank* https://data.worldbank.org/indicator/NY.GDP.MKTP.CD (2023).

---

## Acknowledgements

The authors thank P. Salamon at the European Commission's Joint Research Centre for providing GloFAS version 4 data, and for his insight with the analysis of that data.

## Author Contributions

G.N. conducted experiments and analyses and wrote the first paper draft that was edited by all co-authors. G.S., F.K. and O.G. contributed substantially to experimental design and the design of the figures. All Google-affiliated authors contributed to development of the AI model. Authors with ECMWF affiliation (S.H., F.P. and C.P.) additionally helped to ensure proper processing of GloFAS data. S.N. completed the work while at Google. Y.M. supervised the research.

## Competing Interests

The authors declare no competing interests.

---

*© The Author(s) 2024. Open Access — Licensed under Creative Commons Attribution 4.0 International License (CC BY 4.0). http://creativecommons.org/licenses/by/4.0/*
