"""
Data-grounded prompt templates for FloodOps LLM reasoning.

CRITICAL: These are NOT generic "You are a flood expert" prompts.
Every prompt templates in ACTUAL sensor values, z-scores, ensemble
counts, and timestamps. The LLM must cite specific numbers and
express genuine uncertainty.
"""

SPATIAL_REASONING = """You are generating a risk explanation for zone {zone_id} ({zone_name}).

ACTUAL DATA (do not invent numbers — use only these):
- Upstream gauge {gauge_id}: {gauge_value}m ({z_score}σ deviation, last reading {minutes_ago}min ago)
- Soil saturation: {soil_pct}% (source: {soil_source}, last update: {soil_age})
- ECMWF ensemble: {n_members_flood}/{total_members} members predict >{depth_threshold}m depth
- Current phase: {current_phase}, entered {phase_duration} ago

RULES:
1. Cite specific numbers. Never say "high rainfall" — say "142mm in 24h, which is 2.8σ above the 30-day mean."
2. Quantify confidence as a fraction: "38 of 50 ensemble members agree."
3. If members disagree, SHOW BOTH VIEWS. Explain what the minority members see differently.
4. State what data is MISSING or STALE. If SAR data is 4 days old, say so.
5. Express genuine uncertainty. If the forecast could go either way, say "This is a close call because..."
6. Do not use words like "catastrophic" unless >80% of members support that outcome.
"""

TRANSITION_JUSTIFICATION = """Justify the phase transition from {from_phase} to {to_phase}.

TRIGGERING DATA:
{trigger_data_json}

GATE CONDITIONS:
{gate_conditions_json}

RULES:
1. Be specific: "FloodPredictAgent reports max probability 0.83, exceeding the 0.70 threshold."
2. Acknowledge what could make this a false alarm.
3. State what would need to happen for de-escalation.
4. If any gate condition was borderline, flag it explicitly.
"""

SITREP = """Generate a situation report for emergency decision-makers.

CURRENT STATE:
- Phase: {current_phase}
- Active alerts: {n_alerts}
- Forecasts generated: {n_forecasts}
- Max flood probability: {max_prob:.0%}
- Estimated population at risk: {pop_at_risk:,}

FORMAT:
1. ONE-LINE SUMMARY (start with the severity level and key number)
2. KEY THREAT (what specifically is happening, with numbers)
3. FORECAST CONFIDENCE (what the ensemble agrees/disagrees on)
4. RECOMMENDED ACTIONS (specific, actionable, phase-appropriate)
5. DATA GAPS (what information is missing or stale)
"""

ANOMALY_INTERPRETATION = """Interpret this sensor anomaly for the spatial "why" card.

ANOMALY DATA:
- Sensor: {sensor_id} ({metric})
- Current value: {value} {unit}
- Z-score: {z_score}σ (baseline: {baseline_mean} ± {baseline_std})
- Agreeing sensors: {agreeing_count}/{total_sensors} in watershed
- Timestamp: {timestamp}

CONTEXT:
- Current phase: {current_phase}
- Recent trend: {trend_description}

RULES:
1. Translate the z-score to plain language: "This reading is 3.2 standard deviations above the 30-day average of X."
2. Explain what this MEANS physically: rising water, saturated ground, etc.
3. Note how many independent sensors agree — this affects confidence.
4. If the z-score is borderline (near a threshold), say so.
"""
