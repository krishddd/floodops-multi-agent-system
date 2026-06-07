import { useState } from "react";

const MONO = "'Space Mono', monospace";
const SANS = "'Source Sans 3', sans-serif";

const AGENTS = [
  {
    num:"01", name:"SentinelAgent", lang:"Python", trigger:"iii CRON (15 min + 6-day)",
    role:"Continuous environmental sensing — base data layer",
    solves:"All four flood problems (shared foundation)",
    bg:"#E6F1FB", bdr:"#85B7EB", col:"#0C447C",
    why:"Every other agent needs clean, anomaly-flagged sensor data. Rather than each agent polling raw satellite APIs independently, SentinelAgent centralizes sensor fusion and normalization across 5 data sources. Other agents subscribe only to anomaly events — they never touch raw sensor APIs. This also means all anomaly thresholds are configured in one place, per watershed.",
    inputs:[
      {src:"Sentinel-1 SAR (ESA)", detail:"Cloud-penetrating radar · 10m resolution · 6-day cycle — works in rain and at night"},
      {src:"NOAA GOES-16/17", detail:"Weather radar + rainfall estimates · 15-min intervals · continental/regional coverage"},
      {src:"Global river gauge network", detail:"USGS (US) + GRDC (global) · water level and discharge · 15-min intervals"},
      {src:"ESA CCI Soil Moisture", detail:"Surface saturation index · daily updates · 25 km resolution — affects runoff ratio"},
      {src:"GLIMS Glacier Database", detail:"Baseline lake inventory: area, elevation, dam type for 3,000+ glacial lakes"},
    ],
    logic:[
      "Rolling baseline: maintains 30, 90, and 365-day mean and std per watershed per metric.",
      "Anomaly scoring: z-score of current reading vs baseline. Thresholds configurable per region (arid vs. tropical differ significantly).",
      "Multi-sensor confidence: alert only raised when 2+ independent sensors agree on anomaly direction, reducing false positives.",
      "Severity levels: LOW (>1.5σ) · MEDIUM (>2.5σ) · HIGH (>3.5σ) · CRITICAL (>5σ or confirmed GLOF signals).",
    ],
    fns:[
      "poll_weather_data() — 15-min cron",
      "scan_glacial_lakes() — 6-day cron per lake",
      "check_river_gauges() — 15-min cron",
      "detect_anomaly(metric, value, watershed_id) → AnomalyAlert",
      "emit_alert(level, anomaly) → queue → FloodPredictAgent",
    ],
    outputs:["AnomalyAlert { level, metric, location, deviation_sigma, confidence }"],
    connects:["→ FloodPredictAgent (via anomaly queue)","→ GLOFAgent (glacial-specific alerts)","→ DiseaseRiskAgent (flood extent data post-event)"],
    code:`@function
@trigger.cron("*/15 * * * *")
async def poll_all_sensors(self) -> None:
    readings = await asyncio.gather(
        self.noaa.get_rainfall(),
        self.gauges.get_river_levels(),
        self.esa.get_soil_moisture(),
    )
    for reading in flatten(readings):
        baseline = await self.db.get_baseline(reading.watershed_id)
        z_score  = (reading.value - baseline.mean) / baseline.std
        if abs(z_score) > self.thresholds[reading.metric]:
            await self.queue.emit(AnomalyAlert(
                level    = self.severity(abs(z_score)),
                metric   = reading.metric,
                location = reading.location,
                deviation= z_score,
            ))`
  },
  {
    num:"02", name:"FloodPredictAgent", lang:"Python", trigger:"queue ← SentinelAgent OR GLOFAgent",
    role:"Probabilistic flood forecasting engine",
    solves:"Flash flood warning (problem 1) + Glacial lake outbursts (problem 4)",
    bg:"#EEEDFE", bdr:"#AFA9EC", col:"#26215C",
    why:"Detecting heavy rainfall is not the same as predicting a flood. FloodPredictAgent converts sensor anomalies into spatial probability estimates by combining probabilistic weather forecasting with watershed hydraulic routing and a continuously self-improving ML bias-correction model. The key insight: run 10,000 scenarios from weather uncertainty, not just one best-guess forecast. This is the model autoresearch improves overnight — every confirmed flood event adds new labeled training data.",
    inputs:[
      {src:"SentinelAgent AnomalyAlert", detail:"Rainfall anomaly level, soil moisture state, upstream river levels — the triggering signal"},
      {src:"GLOFAgent lake data", detail:"Lake volume delta + dam integrity score — feeds glacial-triggered flood scenarios"},
      {src:"ECMWF ensemble forecast", detail:"50-member weather ensemble · 10-day horizon · downloaded 4× daily via API"},
      {src:"HydroSHEDS river network", detail:"Global river topology and drainage basins at 90 m resolution for hydraulic routing"},
      {src:"SRTM / TanDEM-X DEM", detail:"30 m digital elevation model — determines how water flows through the watershed"},
      {src:"Dartmouth Flood Observatory archive", detail:"30+ years of global flood events for ML model training and validation"},
    ],
    logic:[
      "Monte Carlo ensemble: sample from ECMWF 50-scenario uncertainty × soil moisture uncertainty = ~10,000 scenarios per event.",
      "Per-scenario hydraulic routing: simplified HEC-RAS model routes rainfall through watershed DEM → flood extent, depth, and peak timing per scenario.",
      "Aggregation: build spatial probability map from ensemble (% of 10k scenarios that flood each 30m grid cell).",
      "ML correction: EfficientNet-B3 spatial model corrects systematic hydrological model bias using labeled historical events — trained by autoresearch overnight loop.",
      "GLOF specialization: for glacial lake events, skip rainfall ensemble; route lake breach volume directly through downstream DEM to calculate impact zone.",
    ],
    fns:[
      "run_ensemble(watershed_id, alert) → FloodScenario[10_000]",
      "route_scenario(scenario, dem, river_net) → FloodExtent",
      "aggregate_scenarios(extents) → ProbabilisticFloodMap",
      "ml_correct(hydro_map, dem_features) → CorrectedFloodMap",
      "estimate_glof_impact(lake_id, breach_volume, dem) → GLOFExtent",
    ],
    outputs:[
      "ProbabilisticFloodMap { cell_id: probability [0–1] }",
      "FloodTiming { peak_time: datetime, confidence_interval_hours: float }",
      "FloodDepth { cell_id: depth_m, uncertainty_m }",
    ],
    connects:["← SentinelAgent (triggers on anomaly queue)","← GLOFAgent (probabilistic GLOF risk)","→ AlertAgent (flood probability drives alert level)","→ UrbanRiskAgent (flood extent map for city-layer intersection)"],
    code:`@function
@trigger.queue("anomaly_alerts")
async def predict_flood(self, alert: AnomalyAlert) -> FloodForecast:
    watershed = await self.hydro_db.get_watershed(alert.location)
    scenarios = await self.ecmwf.get_ensemble(
        bbox=watershed.bbox, n_members=10_000
    )
    # parallel hydraulic routing — CPU-intensive, run in process pool
    extents = await asyncio.gather(*[
        self.route_hydraulic(s, watershed.dem, watershed.river_net)
        for s in scenarios
    ])
    prob_map  = self.aggregate(extents)
    corrected = self.ml_model.correct(prob_map, dem_features=watershed.features)
    return FloodForecast(
        probability_map = corrected,
        peak_time       = self.estimate_peak(extents),
        confidence      = self.confidence_interval(extents, p=0.9),
    )`
  },
  {
    num:"03", name:"GLOFAgent", lang:"Python", trigger:"iii CRON (6-day) + direct HTTP trigger",
    role:"Glacial Lake Outburst Flood specialist",
    solves:"Glacial lake outbursts (problem 4)",
    bg:"#E1F5EE", bdr:"#9FE1CB", col:"#04342C",
    why:"Glacial Lake Outburst Floods have almost no rainfall signal. They occur with minutes of warning once a moraine or ice dam breaches, and no weather radar picks them up. They require satellite-derived lake volume tracking and dam structural integrity modeling — fundamentally different from rainfall prediction. Critically: confirmed GLOF breaches route DIRECTLY to AlertAgent, bypassing the FloodPredictAgent queue entirely, because there is no time to wait for an ensemble model.",
    inputs:[
      {src:"Sentinel-1 SAR + Sentinel-2 optical", detail:"Lake surface area tracking · 10 m resolution · 6-day cycle · SAR works through cloud cover"},
      {src:"ICESat-2 laser altimetry", detail:"Lake surface elevation at cm accuracy · 91-day repeat cycle — detects slow lake filling"},
      {src:"Planet Labs (priority lakes)", detail:"Daily optical imagery for the 50 highest-risk lakes when licensed"},
      {src:"GLIMS glacier inventory", detail:"Baseline lake area, elevation, dam type (moraine vs. ice) for 3,000+ lakes"},
      {src:"Carrivick & Tweed GLOF database", detail:"1,348 documented historical GLOFs — training data for breach probability model"},
    ],
    logic:[
      "Volume tracking: lake area from SAR + depth-area empirical relationship → volume estimate. Alert if 6-day volume delta exceeds watershed-specific threshold.",
      "Dam integrity scoring: moraine dam — DEM differencing detects erosion. Ice dam — SAR coherence detects ice thinning. Score: 0 (failed) → 1 (stable).",
      "Downstream routing: given a breach scenario, route lake volume through DEM to generate impact zone map and time-to-impact estimates.",
      "Direct alert bypass: confirmed breach (integrity score < 0.3) → immediate AlertAgent HTTP call. No queue delay. This saves the minutes that matter.",
    ],
    fns:[
      "monitor_all_lakes() — 6-day cron for all 500 monitored lakes",
      "calculate_lake_volume(lake_id, sar_image) → VolumeEstimate",
      "score_dam_integrity(lake_id, sar_coherence, dem_diff) → float [0–1]",
      "model_breach_impact(lake_id, volume, dem) → ImpactZone",
      "emit_glof_alert(lake_id, severity) → FloodPredictAgent OR AlertAgent direct",
    ],
    outputs:[
      "LakeHealthReport { lake_id, volume_m3, volume_delta_m3, integrity_score, risk_level }",
      "ImpactZone { geometry, peak_discharge_m3s, time_to_impact_minutes }",
    ],
    connects:["→ FloodPredictAgent (probabilistic GLOF risk input)","→ AlertAgent DIRECTLY on confirmed breach (bypasses all queues — time critical)"],
    code:`@function
@trigger.cron("0 6 */6 * *")         # every 6 days
async def monitor_all_lakes(self) -> None:
    lakes = await self.glims.get_monitored_lakes()
    for lake in lakes:
        sar       = await self.sentinel.get_sar(lake.bbox)
        volume    = self.calculate_volume(sar, lake.depth_model)
        integrity = self.score_dam(lake, sar.coherence)

        if integrity < 0.3:                  # breach imminent/confirmed
            impact = self.model_breach(lake, volume.current, lake.dem)
            # DIRECT call — no queue — seconds matter
            await self.alert_agent.trigger_glof_emergency(
                lake_id=lake.id, impact=impact,
                tta_minutes=impact.time_to_impact,
            )
        elif volume.delta > lake.volume_threshold:
            await self.queue.emit(GLOFProbabilisticAlert(
                lake_id=lake.id, volume_delta=volume.delta,
                integrity=integrity,
            ))`
  },
  {
    num:"04", name:"UrbanRiskAgent", lang:"Python", trigger:"queue ← FloodPredictAgent + HTTP (recovery phase)",
    role:"City vulnerability mapping and redesign intelligence",
    solves:"Cities built on old rainfall patterns (problem 2)",
    bg:"#FAEEDA", bdr:"#EF9F27", col:"#412402",
    why:"River flood models output water depth in a field. Urban flood models must answer which street is impassable, which building has 200 people on the ground floor, which drainage pipe will overflow first, and which road leads to a shelter. These require entirely different inputs (OSM buildings, drainage topology, impervious surface fractions) and different models. UrbanRiskAgent also generates the long-term redesign recommendations — identifying exactly which infrastructure is operating beyond its design rainfall envelope after each event.",
    inputs:[
      {src:"OpenStreetMap", detail:"Roads, buildings, and drainage network topology — the structural map of the city"},
      {src:"WorldPop population grids", detail:"100 m resolution population density · updated annually · used for exposure calculation"},
      {src:"ESA WorldCover impervious surface", detail:"10 m fraction of concrete/asphalt vs. permeable ground — drives runoff ratio calculation"},
      {src:"SRTM urban DEM + LiDAR", detail:"30 m base DEM supplemented with LiDAR where available — critical for precise street-level routing"},
      {src:"FloodPredictAgent output", detail:"Probabilistic flood extent map to intersect with urban layers"},
      {src:"EMDAT damage database", detail:"Historical damage events for model calibration and redesign prioritization"},
    ],
    logic:[
      "Pre-flood risk map: vulnerability index per cell = elevation rank + population density + impervious fraction + inverse(drainage_capacity).",
      "Inundation intersection: overlay FloodPredictAgent extent probability with building and road layers → at-risk count and critical asset exposure per zone.",
      "Evacuation routing: A* pathfinding on road graph, dynamically blocking edges as flood front advances in predicted path. Updates every 30 min during active event.",
      "Drainage capacity gap: compare design rainfall standard (e.g. 1-in-100-year event from original infrastructure specs) vs. current observed extremes → identify infrastructure that is definitionally undersized for today's climate.",
      "Post-flood damage: pre/post Sentinel-2 comparison using NDVI and SAR backscatter change detection → damage polygons with area and building count.",
    ],
    fns:[
      "build_risk_map(city_id) → VulnerabilityMap  — runs daily, pre-computes city risk",
      "identify_at_risk_zones(flood_map, city_id) → ZoneRiskReport",
      "calculate_evacuation_routes(flood_extent, pop_map) → RouteSet",
      "assess_post_flood_damage(pre_img, post_img) → DamagePolygons",
      "generate_redesign_priorities(city_id, event_history) → UpgradeList",
    ],
    outputs:[
      "ZoneRiskReport { zone_id: { population, risk_level, drainage_gap, key_assets } }",
      "RouteSet { zone_id: { safe_roads[], shelters[], estimated_capacity } }",
      "UpgradeList { infrastructure_id, design_gap_mm, cost_usd, risk_reduction_pct }",
    ],
    connects:["← FloodPredictAgent (receives flood extent map)","→ AlertAgent (zone-level risk + evacuation routes for public broadcast)","→ ResourceAgent (at-risk population per zone drives supply calculation)"],
    code:`@function
@trigger.queue("flood_forecasts")
async def map_urban_risk(self, forecast: FloodForecast) -> UrbanRiskReport:
    city   = await self.osm.get_urban_layers(forecast.bbox)
    pop    = await self.worldpop.get_density(forecast.bbox)
    design = await self.infra_db.get_design_standards(city.id)

    zones  = self.intersect(forecast.probability_map, city.buildings, pop)
    routes = self.pathfind(
        graph    = city.road_graph,
        blocked  = forecast.high_prob_cells(p_threshold=0.7),
        origins  = zones.high_risk_centroids,
        targets  = city.shelters,
    )
    gaps = self.calc_drainage_gap(city, design, forecast)
    return UrbanRiskReport(zones=zones, routes=routes, drainage_gaps=gaps)`
  },
  {
    num:"05", name:"AlertAgent", lang:"TypeScript", trigger:"queue ← FloodPredictAgent + HTTP direct ← GLOFAgent",
    role:"Multi-channel, multi-language warning dissemination",
    solves:"Flash flood warning last-mile problem (problem 1)",
    bg:"#FCEBEB", bdr:"#F09595", col:"#501313",
    why:"The hardest part of flood warning is not prediction — it is getting a message to a farmer in rural Bangladesh at 2 AM, in Bangla, telling them specifically which road is still passable. AlertAgent handles all telecom integrations: SMS cell broadcast (broadcasts to every phone in a cell tower's coverage area — no phone number list needed), radio scripts localized per region, and municipal siren activation codes. It also handles real-time route updates as the flood spreads and roads become impassable.",
    inputs:[
      {src:"FloodPredictAgent", detail:"Flood probability, peak timing, and geographic extent — determines alert level and geofencing"},
      {src:"UrbanRiskAgent", detail:"Zone-level risk scores, pre-calculated evacuation routes, and shelter locations"},
      {src:"GLOFAgent (direct HTTP)", detail:"Confirmed breach call — bypasses queues and triggers EMERGENCY level immediately"},
      {src:"Cell broadcast system APIs", detail:"National telecom APIs for broadcasting to all phones in a geographic polygon"},
      {src:"Radio station contacts + municipal siren codes", detail:"Pre-configured per region during system setup"},
    ],
    logic:[
      "Alert level mapping: <40% probability → ADVISORY (app/email only). 40–70% → WATCH (SMS to high-risk zones). 70–90% → WARNING (mass cell broadcast). >90% or confirmed GLOF → EMERGENCY (all channels simultaneously).",
      "Geofencing: only alert people physically inside the projected flood polygon + 20% buffer — avoids panic in unaffected areas.",
      "Language detection: infer from cell tower location + carrier MCC-MNC code → region's primary language. Fallback: broadcast in top 3 languages of the region.",
      "Escalation timing: WATCH → WARNING transition triggers re-broadcast even if people already received WATCH alert, with updated routing.",
    ],
    fns:[
      "assess_alert_level(probability, timing_hours, source) → AlertLevel",
      "generate_message(level, zone, language, routes) → LocalizedMessage",
      "broadcast_cell(zone_polygon, message) → TelecomAPI call",
      "generate_radio_script(level, zone, language) → RadioBroadcast",
      "activate_sirens(zone_ids, pattern) → MunicipalAPI call",
      "update_routes(zone_id, new_passable_roads) → LiveEvacMap",
    ],
    outputs:[
      "CellBroadcast { zone_polygon, message_text, language, timestamp, reach_estimate }",
      "RadioBroadcast { station_ids[], script_text, language, priority_level }",
      "SirenActivation { zone_ids[], pattern: 'FLOOD_WARNING'|'EMERGENCY', duration_s }",
    ],
    connects:["← FloodPredictAgent","← UrbanRiskAgent","← GLOFAgent (direct HTTP bypass — no queue latency)"],
    code:`@function
@trigger.queue("flood_forecasts")
async function dispatchAlerts(forecast: FloodForecast): Promise<void> {
  const level = assessLevel(forecast.maxProbability, forecast.peakHours);
  const zones = await urbanRisk.getAtRiskZones(forecast.extent);

  for (const zone of zones) {
    const lang    = await detectLanguage(zone.centroid);
    const routes  = await urbanRisk.getEvacRoutes(zone.id);
    const message = renderTemplate(level, zone, lang, routes);

    if (level >= AlertLevel.WATCH) {
      await telecom.cellBroadcast(zone.polygon, message);
    }
    if (level >= AlertLevel.WARNING) {
      await radio.broadcast(zone.stations, renderScript(level, zone, lang));
    }
    if (level === AlertLevel.EMERGENCY) {
      await sirens.activate(zone.sirenIds, { pattern: "FLOOD_EMERGENCY" });
    }
  }
}`
  },
  {
    num:"06", name:"ResourceAgent", lang:"Python", trigger:"queue ← FloodPredictAgent (p>0.5) + queue ← DiseaseRiskAgent",
    role:"Logistics, pre-positioning, and rescue routing",
    solves:"Response efficiency across all four flood problems",
    bg:"#FAECE7", bdr:"#F5C4B3", col:"#4A1B0C",
    why:"Most disaster response is reactive — supplies are ordered after the flood, arrive days later, and cost 3–5× more than pre-positioned equivalents. ResourceAgent uses the prediction window to act before the event: moving supplies to staging areas while roads are still passable. During the active flood it routes rescue teams using the flood extent as a navigable water layer. After the flood it distributes medical supplies to DiseaseRiskAgent-identified hotspots before a single case is reported.",
    inputs:[
      {src:"FloodPredictAgent", detail:"Flood timing and probability — defines the available pre-positioning window (roads must still be passable)"},
      {src:"UrbanRiskAgent", detail:"At-risk population by zone — drives supply quantity calculation"},
      {src:"DiseaseRiskAgent", detail:"Post-flood medical hotspot map — drives post-event distribution routing"},
      {src:"Inventory management system", detail:"Real-time location and quantity of ORS, antibiotics, water purification, rescue boats"},
      {src:"OpenStreetMap road network", detail:"Routing graph for supply vehicles and rescue boats (post-flood = navigable flood extent)"},
    ],
    logic:[
      "Supply calculation: population_at_risk × per-capita ORS sachets + antibiotic courses + water purification tablet days.",
      "Staging area selection: must be (a) outside projected flood zone, (b) within 1-hour truck travel of affected zone, (c) accessible by road that won't flood.",
      "Pre-positioning trigger: flood probability > 50% AND 12+ hours to peak — supplies must move before roads flood.",
      "Rescue routing: during active flood, treat flood extent as navigable water. Route rescue boats to maximize population reached per travel hour.",
      "Medical distribution: post-flood, route supply vehicles to DiseaseRiskAgent hotspots ordered by outbreak probability × population — must arrive before symptom onset.",
    ],
    fns:[
      "calculate_supply_needs(population, flood_severity) → SupplyList",
      "find_staging_areas(flood_extent, road_network) → StagingLocations",
      "generate_movement_orders(inventory, staging, deadline) → LogisticsOrders",
      "route_rescue_teams(flood_extent, population_vulnerability_map) → RescueRoutes",
      "distribute_medical_supplies(disease_risk_map, road_network) → DistributionPlan",
    ],
    outputs:[
      "LogisticsOrders { vehicle_id, route, payload, staging_location, deadline }",
      "RescueRoutes { team_id, route_via_water, target_population, priority_score }",
      "DistributionPlan { zone_id, supply_types, quantity, delivery_window_hours }",
    ],
    connects:["← FloodPredictAgent (triggers on p>0.5)","← UrbanRiskAgent (population data)","← DiseaseRiskAgent (post-flood medical needs)"],
    code:`@function
@trigger.queue("flood_forecasts")
async def preposition_supplies(self, forecast: FloodForecast) -> None:
    if forecast.max_probability < 0.5:
        return  # not worth mobilizing yet

    pop_at_risk = await self.urban.get_population(forecast.high_prob_extent)
    needs       = self.calc_supply_needs(pop_at_risk, forecast.severity)
    staging     = self.select_staging_areas(
        outside_zone   = forecast.flood_extent,
        road_network   = self.osm.roads,
        max_travel_hrs = 1.0,
    )
    available = await self.inventory.find_nearest(staging, needs)
    orders    = self.generate_orders(available, staging,
                    deadline=forecast.peak_time - timedelta(hours=2))
    await self.dispatch(orders)`
  },
  {
    num:"07", name:"DiseaseRiskAgent", lang:"Python", trigger:"queue ← SentinelAgent (flood-receding event)",
    role:"Post-flood disease outbreak prediction and prevention",
    solves:"Cholera, typhoid, leptospirosis after every flood (problem 3)",
    bg:"#FBEAF0", bdr:"#F0C4D4", col:"#4B1528",
    why:"Every major flood is followed by a disease outbreak. This is not unpredictable — cholera has a 2–5 day incubation, typhoid 6–30 days, leptospirosis 2–30 days. Location is also predictable: high-density areas, poor sanitation, contaminated water sources. The intervention window is the incubation period: if medical supplies reach a neighborhood before symptoms appear, an outbreak is preventable. DiseaseRiskAgent exists entirely to operate in that window.",
    inputs:[
      {src:"SentinelAgent flood extent data", detail:"Flood depth, extent, and duration — primary drivers of contamination spread and pathogen survival"},
      {src:"WorldPop population density", detail:"100 m resolution population — determines exposure magnitude per hotspot"},
      {src:"JMP WASH infrastructure data", detail:"Pre-mapped water sources, sanitation coverage gaps — determines vulnerability baseline"},
      {src:"WHO EWARN / DHIS2", detail:"Historical outbreak patterns: which flood profiles led to which outbreaks in similar settings"},
      {src:"ECMWF temperature + humidity forecast", detail:"Warm, humid conditions accelerate Vibrio cholerae and Leptospira survival in standing water"},
    ],
    logic:[
      "Cholera risk model: P(cholera) ∝ flood_depth × flood_duration × (1 − sanitation_coverage) × population_density.",
      "Typhoid risk model: P(typhoid) ∝ P(drinking_water_contaminated) × population_without_piped_water_pct.",
      "Leptospirosis model: P(lepto) ∝ flood_extent_km2 × rodent_habitat_fraction × outdoor_worker_fraction.",
      "Temporal model: outputs risk in three windows — 0–7 days, 7–14 days, 14–30 days post-flood — matching incubation ranges.",
      "Hotspot thresholding: grid cells where any pathogen risk > 0.7 trigger ResourceAgent supply order with location and quantity.",
    ],
    fns:[
      "calculate_disease_risk(flood_data, population, wash) → DiseaseRiskMap",
      "identify_hotspots(risk_map, threshold=0.7) → HotspotList",
      "estimate_outbreak_timing(flood_end_date, pathogen) → TimingForecast",
      "generate_supply_orders(hotspots, population) → MedicalSupplyList → ResourceAgent",
      "monitor_surveillance(zone_ids) → EarlyWarningSurveillanceFeed",
    ],
    outputs:[
      "DiseaseRiskMap { cell_id: { cholera, typhoid, leptospirosis } [0–1], time_window }",
      "HotspotList { zone_id, pathogen, risk_score, peak_date, population_exposed }",
      "MedicalSupplyList { zone_id, ORS_sachets, antibiotic_courses, water_tabs }",
    ],
    connects:["← SentinelAgent (receives flood extent and duration data)","→ ResourceAgent (supply orders must arrive before symptom onset)"],
    code:`@function
@trigger.queue("flood_receding")
async def forecast_disease_risk(self, event: FloodRecedingEvent) -> DiseaseRiskMap:
    flood = await self.sentinel.get_flood_summary(event.zone_id)
    pop   = await self.worldpop.get_density(event.bbox)
    wash  = await self.jmp.get_sanitation_coverage(event.bbox)
    temp  = await self.ecmwf.get_forecast(event.bbox, days=30)

    risk = self.epi_model.predict({
        "cholera":  self.cholera_model(flood, pop, wash),
        "typhoid":  self.typhoid_model(flood, pop, wash),
        "lepto":    self.lepto_model(flood, pop, temp),
    })
    hotspots = [z for z in risk.zones if z.max_risk > 0.7]
    if hotspots:
        orders = self.calc_medical_needs(hotspots, pop)
        await self.resource_agent.distribute_medical_supplies(orders)
    return risk`
  },
  {
    num:"ORC", name:"FloodOps Orchestrator", lang:"Python (LangGraph)", trigger:"Event-driven — reacts to all agent outputs",
    role:"LangGraph state machine — the coordination brain",
    solves:"Coordinates all 7 agents across the full event lifecycle",
    bg:"#F1EFE8", bdr:"#B4B2A9", col:"#2C2C2A",
    why:"Without an orchestrator, agents act independently on their own triggers and don't share state. FloodOps knows the system is currently in IMMINENT_THREAT for watershed A, that UrbanRiskAgent finished mapping zone 3 but not zone 4, and that GLOFAgent raised a concurrent alert for a different lake while the rainfall flood is still active. It handles compound events, prevents conflicting resource allocation, tracks agent completion before phase transitions, and maintains a full audit trail for every decision.",
    inputs:[
      {src:"All 7 agent event queues", detail:"Subscribes to outputs from every agent — maintains global event state"},
      {src:"System configuration", detail:"Regional thresholds, escalation rules, resource constraints, operator overrides"},
    ],
    logic:[
      "LangGraph StateGraph: 7 nodes (one per phase), conditional edges driven by FloodPredictAgent probability thresholds and phase completion checks.",
      "Compound event handling: multiple concurrent alerts → merge into coordinated response, deduplicate resource allocation.",
      "Agent completion gating: will NOT issue evacuation order until UrbanRiskAgent mapping is confirmed complete — avoids routing people to unknown roads.",
      "Rollback: if FloodPredictAgent probability drops below threshold mid-escalation, de-escalates alerts and notifies all channels.",
      "Audit trail: every state transition, agent call, and decision is logged with timestamp, input values, confidence, and responsible agent.",
    ],
    fns:[
      "process_alert(alert) → state_transition OR compound_merge",
      "check_gate_conditions(phase, required_agents) → bool",
      "coordinate_phase(phase, agents) → PhaseResult",
      "handle_compound_event(alerts[]) → MergedEventResponse",
      "log_decision(action, reasoning, confidence) → AuditEntry",
    ],
    outputs:[
      "StateTransitionEvent { from_phase, to_phase, trigger_agent, timestamp }",
      "CoordinationOrder { target_agent, action, parameters, deadline }",
      "AuditLog — complete decision trail for post-event debrief and model improvement",
    ],
    connects:["↔ All 7 agents bidirectionally","→ External: emergency management APIs, UN OCHA feeds, national disaster agencies"],
    code:`from langgraph.graph import StateGraph, END

graph = StateGraph(FloodSystemState)
graph.add_node("monitoring",   monitoring_node)
graph.add_node("elevated",     elevated_node)
graph.add_node("imminent",     imminent_node)
graph.add_node("evacuation",   evacuation_node)
graph.add_node("active_flood", active_flood_node)
graph.add_node("post_flood",   post_flood_node)
graph.add_node("recovery",     recovery_node)

graph.add_conditional_edges("monitoring", route_monitoring, {
    "elevated": "elevated", "continue": "monitoring",
})
graph.add_conditional_edges("elevated", route_elevated, {
    "imminent": "imminent", "deescalate": "monitoring",
})
# ... remaining transitions

async def route_monitoring(state: FloodSystemState) -> str:
    alert = state.latest_sentinel_alert
    if alert and alert.level >= AlertLevel.MEDIUM:
        await agents.flood_predict.run_ensemble(alert.watershed_id)
        return "elevated"
    return "continue"`
  },
];

export default function App() {
  const [sel, setSel] = useState(1); // Start on FloodPredictAgent
  const [openSec, setOpenSec] = useState(null);
  const a = AGENTS[sel];

  const SEC = [
    { id:"why",     label:"why this agent exists" },
    { id:"inputs",  label:"data inputs" },
    { id:"logic",   label:"core logic" },
    { id:"fns",     label:"functions + outputs" },
    { id:"code",    label:"iii worker code" },
    { id:"conn",    label:"connections" },
  ];

  return (
    <div style={{display:"flex",height:"100%",fontFamily:SANS,color:"var(--color-text-primary)",minHeight:540}}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Source+Sans+3:ital,wght@0,400;0,500;1,400&display=swap');
      .agent-btn{display:flex;align-items:center;gap:8px;width:100%;padding:9px 12px;border:none;background:transparent;cursor:pointer;text-align:left;border-bottom:0.5px solid var(--color-border-tertiary);transition:background .1s}
      .agent-btn:hover{background:var(--color-background-secondary)}
      .agent-btn.active-btn{background:var(--color-background-secondary)}
      .sec-btn{display:flex;justify-content:space-between;align-items:center;width:100%;padding:9px 0;border:none;background:transparent;cursor:pointer;border-bottom:0.5px solid var(--color-border-tertiary);text-align:left}
      .sec-btn:hover{opacity:.7}
      .fn-line{font-family:'Space Mono',monospace;font-size:10px;padding:4px 0;border-bottom:0.5px dotted var(--color-border-tertiary);color:var(--color-text-secondary);line-height:1.5}
      .fn-line:last-child{border-bottom:none}
      .input-row{display:grid;grid-template-columns:170px 1fr;gap:0;border-bottom:0.5px solid var(--color-border-tertiary);padding:7px 0}
      .input-row:last-child{border-bottom:none}
      `}</style>

      {/* Left sidebar */}
      <div style={{width:200,minWidth:200,borderRight:"0.5px solid var(--color-border-tertiary)",display:"flex",flexDirection:"column",overflowY:"auto"}}>
        <div style={{padding:"10px 12px",borderBottom:"0.5px solid var(--color-border-tertiary)"}}>
          <div style={{fontFamily:MONO,fontSize:9,color:"var(--color-text-tertiary)",letterSpacing:".05em"}}>flood multi-agent system</div>
          <div style={{fontFamily:MONO,fontSize:11,fontWeight:700,marginTop:2}}>8 agents total</div>
        </div>
        {AGENTS.map((ag,i)=>(
          <button key={i} className={`agent-btn${sel===i?" active-btn":""}`} onClick={()=>setSel(i)}>
            <div style={{width:3,height:28,borderRadius:2,background:ag.col,flexShrink:0}}></div>
            <div>
              <div style={{fontFamily:MONO,fontSize:9,color:"var(--color-text-tertiary)",letterSpacing:".04em"}}>agent {ag.num}</div>
              <div style={{fontSize:12,fontWeight:500,lineHeight:1.3,color:sel===i?"var(--color-text-primary)":"var(--color-text-secondary)"}}>{ag.name}</div>
            </div>
          </button>
        ))}
      </div>

      {/* Main panel */}
      <div style={{flex:1,overflowY:"auto",padding:"20px 24px"}}>
        {/* Agent header */}
        <div style={{borderLeft:`4px solid ${a.col}`,paddingLeft:14,marginBottom:20}}>
          <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:4,flexWrap:"wrap"}}>
            <span style={{fontFamily:MONO,fontSize:10,fontWeight:700,color:a.col}}>agent {a.num}</span>
            <span style={{fontFamily:MONO,fontSize:9,padding:"2px 7px",borderRadius:3,background:a.bg,color:a.col}}>{a.trigger}</span>
            <span style={{fontFamily:MONO,fontSize:9,padding:"2px 7px",borderRadius:3,background:"var(--color-background-secondary)",color:"var(--color-text-secondary)",border:"0.5px solid var(--color-border-tertiary)"}}>{a.lang}</span>
          </div>
          <h2 style={{fontFamily:MONO,fontSize:18,fontWeight:700,margin:"0 0 4px",color:a.col}}>{a.name}</h2>
          <p style={{fontSize:13,color:"var(--color-text-secondary)",margin:"0 0 5px",lineHeight:1.5}}>{a.role}</p>
          <p style={{fontFamily:MONO,fontSize:10,color:"var(--color-text-tertiary)",margin:0}}>solves → {a.solves}</p>
        </div>

        {/* Sections */}
        {SEC.map(s=>{
          const open = openSec===s.id || (s.id==="why"&&openSec===null);
          return (
            <div key={s.id} style={{marginBottom:4,border:"0.5px solid var(--color-border-tertiary)",borderRadius:8,overflow:"hidden"}}>
              <button className="sec-btn" style={{padding:"10px 14px",borderBottom:open?"0.5px solid var(--color-border-tertiary)":"none"}}
                onClick={()=>setOpenSec(open&&s.id!=="why"?null:s.id)}>
                <span style={{fontFamily:MONO,fontSize:10,fontWeight:700,color:"var(--color-text-secondary)",letterSpacing:".04em"}}>{s.label.toUpperCase()}</span>
                <span style={{fontFamily:MONO,fontSize:12,color:"var(--color-text-tertiary)"}}>{open?"−":"+"}</span>
              </button>
              {open&&(
                <div style={{padding:"12px 14px",background:"var(--color-background-secondary)"}}>
                  {s.id==="why"&&<p style={{fontSize:13,lineHeight:1.7,margin:0}}>{a.why}</p>}
                  {s.id==="inputs"&&a.inputs.map((inp,i)=>(
                    <div key={i} className="input-row">
                      <span style={{fontFamily:MONO,fontSize:11,fontWeight:700,color:a.col,paddingRight:12,lineHeight:1.4}}>{inp.src}</span>
                      <span style={{fontSize:12,color:"var(--color-text-secondary)",lineHeight:1.5}}>{inp.detail}</span>
                    </div>
                  ))}
                  {s.id==="logic"&&(
                    <ul style={{margin:0,paddingLeft:16,display:"flex",flexDirection:"column",gap:8}}>
                      {a.logic.map((l,i)=><li key={i} style={{fontSize:12,lineHeight:1.6}}>{l}</li>)}
                    </ul>
                  )}
                  {s.id==="fns"&&(
                    <div>
                      <div style={{fontFamily:MONO,fontSize:9,color:"var(--color-text-tertiary)",letterSpacing:".05em",marginBottom:6}}>KEY FUNCTIONS</div>
                      <div style={{marginBottom:14}}>{a.fns.map((f,i)=><div key={i} className="fn-line">{f}</div>)}</div>
                      <div style={{fontFamily:MONO,fontSize:9,color:"var(--color-text-tertiary)",letterSpacing:".05em",marginBottom:6}}>OUTPUTS</div>
                      {a.outputs.map((o,i)=>(
                        <div key={i} style={{fontFamily:MONO,fontSize:11,padding:"5px 8px",borderRadius:4,background:a.bg,color:a.col,marginBottom:4,lineHeight:1.4}}>{o}</div>
                      ))}
                    </div>
                  )}
                  {s.id==="code"&&(
                    <pre style={{fontFamily:MONO,fontSize:11,lineHeight:1.75,margin:0,overflowX:"auto",color:"var(--color-text-primary)",whiteSpace:"pre"}}>{a.code}</pre>
                  )}
                  {s.id==="conn"&&a.connects.map((c,i)=>(
                    <div key={i} style={{fontFamily:MONO,fontSize:11,padding:"5px 0",borderBottom:"0.5px dotted var(--color-border-tertiary)",color:"var(--color-text-secondary)"}}>{c}</div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
