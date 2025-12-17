from __future__ import annotations
from typing import Dict, Any, Optional, List
import datetime as dt
import json
from typing import Optional

from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from common.config import settings, logger

Band = Optional[str]  # "good" | "normal" | "critical" | None

# Lower indices are worse. Used for computing step size between bands.
BAND_ORDER = {"critical": 0, "normal": 1, "good": 2}

# Score model for transitions, reflecting both direction and magnitude.
# Note: a two-step jump (critical -> good) counts double.
TRANSITION_SCORE = {
    ("critical", "normal"): +1,
    ("normal",   "good"):   +1,
    ("critical", "good"):   +2,
    ("good",     "normal"): -1,
    ("normal",   "critical"):-1,
    ("good",     "critical"):-2,
}

# These sets are used to quickly test if a given (from_band, to_band) pair
# should be considered a positive movement (POSITIVE_UP) or a cautionary
# movement (CAUTION_DOWN) for flagging purposes.
POSITIVE_UP = {("critical","normal"), ("critical","good"), ("normal","good")}
CAUTION_DOWN = {("good","normal"), ("good","critical"), ("normal","critical")}

def _parse_date(s: str) -> dt.datetime:
    """
    Robust date parser:
    - First tries ISO format (YYYY-MM-DD or full ISO datetime).
    - Then falls back to %Y-%m-%d.
    - If both fail, returns datetime.min so the original order is preserved
      by _older_newer() without raising errors.
    """
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        try:
            return dt.datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            # last-ditch: keep order as given
            return dt.datetime.min

def _older_newer(a_date: str, b_date: str, a_data: Any, b_data: Any):
    """
    Returns ((old_date, old_data), (new_date, new_data)) in chronological order.
    If parsing fails, _parse_date returns datetime.min for both and preserves input order.
    """
    da, db = _parse_date(a_date), _parse_date(b_date)
    if db >= da:
        return (a_date, a_data), (b_date, b_data)
    else:
        return (b_date, b_data), (a_date, a_data)

def _band_for(buckets: Dict[str, Dict[str, Any]], biomarker: str) -> Band:
    """
    Find the band ("good"/"normal"/"critical") that contains the biomarker.
    Returns None if not present in any section.
    """
    for sec in ("good","normal","critical"):
        if biomarker in buckets.get(sec, {}):
            return sec
    return None

def _value_for(buckets: Dict[str, Dict[str, Any]], biomarker: str) -> Optional[float]:
    """
    Extract a numeric value for a biomarker from the bucket map.
    The value can be:
      - a dict with a "value" field
      - a raw int/float/str convertible to float
    Returns None if not found or not convertible.
    """
    for sec in ("good","normal","critical"):
        v = buckets.get(sec, {}).get(biomarker)
        if isinstance(v, dict) and "value" in v:
            try:
                return float(v["value"])
            except:
                return None
        if isinstance(v, (int,float,str)):
            try:
                return float(v)
            except:
                pass
    return None

# ---------------------------------------
# Input-shape adapters and category index
# ---------------------------------------
def adapt_bucketed(d):
    """
    Accepts a dict using legacy keys {"good_biomarkers","normal_biomarkers","critical_biomarkers"}
    and returns a normalized dict with {"good","normal","critical"} keys.

    If the dict already uses "good"/"normal"/"critical", prefer _normalize_buckets().
    """
    return {
        "good":     d.get("good_biomarkers", {}) or {},
        "normal":   d.get("normal_biomarkers", {}) or {},
        "critical": d.get("critical_biomarkers", {}) or {},
    }

def build_category_index_from_lists(cat_to_tests):
    """
    Deprecated helper (kept for compatibility):
    Builds:
      - bm2cat: biomarker -> category key
      - cats:   category key -> {"title": title-cased name}

    Expects {category_key: [test1, test2, ...]}.
    """
    bm2cat = {}
    cats = {}
    for cat_key, tests in cat_to_tests.items():
        title = cat_key.replace("_", " ").title()
        cats[cat_key] = {"title": title}
        for t in tests:
            bm2cat[t] = cat_key
    return bm2cat, cats


def build_category_index(predefined_categories):
    """
    Flexible category index builder. Supports two shapes:

    1) {category_key: {"title": "...", "tests": [biomarker,...]}, ...}
    2) {category_key: [biomarker, biomarker, ...], ...}

    Returns:
      - bm2cat: biomarker -> category key
      - cats:   category key -> {"title": display_title}
    """
    bm2cat = {}
    cats = {}
    for cat_key, val in predefined_categories.items():
        # If given as {"title": "...", "tests": [...]}
        if isinstance(val, dict) and "tests" in val:
            title = val.get("title", cat_key)
            tests = val.get("tests", [])
        else:
            # If given as a plain list: {cat_key: [test1, test2, ...]}
            title = cat_key.replace("_", " ").title()
            tests = val if isinstance(val, list) else []
        cats[cat_key] = {"title": title}
        for t in tests:
            bm2cat[t] = cat_key
    return bm2cat, cats

def _normalize_buckets(b):
    """
    Ensure the input report dict has "good"/"normal"/"critical" keys.
    If it doesn't, try adapting from legacy *_biomarkers keys.
    """
    if any(k in b for k in ("good", "normal", "critical")):
        return b
    # falls back to your stored keys
    return adapt_bucketed(b)

# ------------------------
# Main comparison function
# ------------------------
async def compare_by_bands(
    predefined_ranges: Dict[str, Any],
    report_old: Dict[str, Dict[str, Any]],
    report_new: Dict[str, Dict[str, Any]],
    date_old: str,
    date_new: str,
    *,
    sex: str = "M",  # Reserved for future sex-specific logic (currently unused).
    consider_only_old_present: bool = True,
    per_biomarker_weights: Optional[Dict[str, float]] = None,
    risk_markers_positive: Optional[List[str]] = None,
    risk_markers_caution: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compare two bucketed reports (good/normal/critical) deterministically.

    Arguments:
      - predefined_ranges: category definitions used to map biomarkers -> category.
        (Only the biomarker membership is used here; numeric ranges are NOT evaluated here.)
      - report_old/report_new: dicts like {"good": {...}, "normal": {...}, "critical": {...}}
      - date_old/date_new: strings; ordering is inferred via safe parsing.
      - sex: reserved for future extension (e.g., sex-specific category weighting or flags).
      - consider_only_old_present:
          True  -> Only score biomarkers that exist in the old report (stable domain).
          False -> Score the union of old and new biomarkers.
      - per_biomarker_weights:
          Optional per-biomarker weights, e.g., {"apob": 1.4, "ldl_cholesterol_direct": 1.4}.
      - risk_markers_positive/risk_markers_caution:
          Lists of biomarkers whose favorable/unfavorable transitions should be flagged.

    Returns:
      A dict containing:
        - dates: {"old", "new"}
        - overall: counts of better/same/worse categories + net_score
        - categories: per-category aggregates
        - transitions: per-biomarker transition detail
        - highlights: top improving/regressing categories by net_score
        - flags: Positive/Caution strings (based on provided risk markers)
        - diff: appeared/disappeared biomarkers (domain delta)
    """
    # Ensure chronological ordering; also returns the corresponding reports.
    (old_date, old_b), (new_date, new_b) = _older_newer(date_old, date_new, report_old, report_new)
    old_b = _normalize_buckets(old_b)
    new_b = _normalize_buckets(new_b)

    weights = per_biomarker_weights or {}
    # Map biomarkers to categories and retrieve category metadata (titles).
    bm2cat, cats_meta = build_category_index(predefined_ranges)

    # Determine the comparison domain (set of biomarkers considered for scoring).
    old_biomarkers = set().union(*[set(old_b.get(k, {}).keys()) for k in ("good","normal","critical")])
    new_biomarkers = set().union(*[set(new_b.get(k, {}).keys()) for k in ("good","normal","critical")])
    domain = old_biomarkers if consider_only_old_present else (old_biomarkers | new_biomarkers)

    # Per-category accumulators.
    per_cat = {}  # cat_key -> aggregates/detailed items

    def _ensure_cat(cat_key: str):
        """
        Initialize a category row in per_cat lazily with zeroed counters and
        a place to store per-biomarker transition detail.
        """
        if cat_key not in per_cat:
            per_cat[cat_key] = {
                "title": cats_meta.get(cat_key, {}).get("title", cat_key),
                "improved": 0, "worsened": 0, "same": 0,
                "net_score": 0.0, "weighted_net": 0.0,
                "biomarkers": []  # list of dicts per biomarker transition
            }

    transitions = []  # Flat list of all per-biomarker transition objects.

    # ----------------------
    # Per-biomarker scoring
    # ----------------------
    for biomarker in sorted(domain):
        old_band = _band_for(old_b, biomarker)
        new_band = _band_for(new_b, biomarker)

        # Respect the "only old-present" rule for scoring.
        if consider_only_old_present and old_band is None:
            continue

        cat_key = bm2cat.get(biomarker, "unmapped")  # Fallback bucket if biomarker isn't in any category list.
        _ensure_cat(cat_key)
        w = float(weights.get(biomarker, 1.0))

        trend = "same"
        step = 0
        score = 0

        # Compute trend/score only if both bands are present.
        if old_band is not None and new_band is not None:
            if old_band == new_band:
                trend = "same"; step = 0; score = 0
            else:
                pair = (old_band, new_band)
                score = TRANSITION_SCORE.get(pair, 0)
                step = abs(BAND_ORDER[new_band] - BAND_ORDER[old_band])
                trend = "better" if score > 0 else "worse" if score < 0 else "same"
        elif old_band is not None and new_band is None:
            # Biomarker disappeared in the new report.
            # We do not penalize; simply record trend as "same" with zero score.
            trend = "same"; score = 0
        elif old_band is None and new_band is not None:
            # Biomarker appeared in the new report; for old-only domain, this branch is skipped by the continue above.
            trend = "same"; score = 0

        # Update per-category counters.
        if trend == "better":
            per_cat[cat_key]["improved"] += 1
        elif trend == "worse":
            per_cat[cat_key]["worsened"] += 1
        else:
            per_cat[cat_key]["same"] += 1

        # Update category scores (raw and weighted).
        per_cat[cat_key]["net_score"] += score
        per_cat[cat_key]["weighted_net"] += score * w

        # Record detailed per-biomarker transition (useful for downstream UI/LLM narrative).
        item = {
            "biomarker": biomarker,
            "category": per_cat[cat_key]["title"],
            "from": old_band, "to": new_band,
            "trend": trend, "step": step,
            "score": score, "weight": w,
            "old_value": _value_for(old_b, biomarker),
            "new_value": _value_for(new_b, biomarker),
        }
        per_cat[cat_key]["biomarkers"].append(item)
        transitions.append(item)

    # --------------------------------------------
    # Per-category table (ordered by canonical set)
    # --------------------------------------------
    # Use the incoming predefined_ranges keys to produce a stable category ordering.
    category_order = [k for k in predefined_ranges.keys()]  # canonical order (your 16 categories)
    if "unmapped" in per_cat and "unmapped" not in category_order:
        category_order.append("unmapped")

    categories = []
    better = same = worse = 0
    for k in category_order:
        if k not in per_cat:
            # Category existed in the schema but had no comparable biomarkers.
            title = cats_meta.get(k, {}).get("title", k)
            categories.append({
                "category": title, "key": k,
                "improved": 0, "worsened": 0, "same": 0,
                "net_score": 0, "trend": "same",
            })
            continue

        c = per_cat[k]
        trend = "better" if c["net_score"] > 0 else "worse" if c["net_score"] < 0 else "same"
        categories.append({
            "category": c["title"], "key": k,
            "improved": c["improved"], "worsened": c["worsened"], "same": c["same"],
            "net_score": int(c["net_score"]),  # integer net score for readability
            "trend": trend
        })
        better += (trend == "better")
        same   += (trend == "same")
        worse  += (trend == "worse")

    # ------------------------------
    # Highlights and simple flagging
    # ------------------------------
    # Top up/down categories by net score for concise summaries.
    top_up = sorted(
        [c for c in categories if c["net_score"] > 0],
        key=lambda x: (-x["net_score"], x["category"])
    )[:3]
    top_dn = sorted(
        [c for c in categories if c["net_score"] < 0],
        key=lambda x: (x["net_score"], x["category"])
    )[:3]

    # Build Positive/Caution flags from the specified risk marker lists.
    pos_list = []
    cau_list = []
    rp = set(risk_markers_positive or [])
    rc = set(risk_markers_caution or [])
    for t in transitions:
        pair = (t["from"], t["to"])
        if t["biomarker"] in rp and pair in POSITIVE_UP:
            pos_list.append(f"{t['biomarker']} {t['from']}→{t['to']}")
        if t["biomarker"] in rc and pair in CAUTION_DOWN:
            cau_list.append(f"{t['biomarker']} {t['from']}→{t['to']}")

    # Recompute counts defensively from the final categories table (ensures consistency).
    better = sum(1 for c in categories if c["trend"] == "better")
    same   = sum(1 for c in categories if c["trend"] == "same")
    worse  = sum(1 for c in categories if c["trend"] == "worse")

    # Overall block—aggregated across categories.
    overall = {
        "date_old": old_date, "date_new": new_date,
        "better_categories": better,
        "same_categories": same,
        "worse_categories": worse,
        "net_score": int(sum(c["net_score"] for c in categories)),
    }

    # Domain delta—purely informational (not scored when consider_only_old_present=True)
    appeared = sorted(list(new_biomarkers - old_biomarkers))
    disappeared = sorted(list(old_biomarkers - new_biomarkers))

    # Final structured result (deterministic, UI/LLM friendly)
    return {
        "dates": {"old": old_date, "new": new_date},
        "overall": overall,
        "categories": categories,           # per-category counts + net_score
        "transitions": transitions,         # per-biomarker detail (optional for UI/LLM)
        "highlights": {
            "improvements": [{"category": c["category"], "delta": c["net_score"]} for c in top_up],
            "regressions":  [{"category": c["category"], "delta": c["net_score"]} for c in top_dn],
        },
        "flags": {"Positive": pos_list, "Caution": cau_list},
        "diff": {"appeared": appeared, "disappeared": disappeared},
    }


# function to generate summary using azure inference
async def generate_comparison_summary_using_grok(result):
    try:
        system_prompt = """You are a meticulous medical summarizer for the Centum app.
        - Use only the JSON provided.
        - British English (e.g., prioritise, fibre).
        - Be concise, reassuring, and actionable.
        - Never invent values or units. If a unit is not present in the JSON, omit it.
        - Base all statements on band changes: good, normal, critical.
        - Emphasise meaningful transitions (critical→normal/good, normal→good, good→normal/critical).
        - Treat “net_score” as a direction-of-travel signal, not a clinical diagnosis.
        - If flags are empty, say so plainly.
        - Close with practical next steps (sleep, lifestyle, diet, supplementation, clinical follow-ups) tailored to observed issues.
        """

        # Inject your Python `result` dict below (e.g., json.dumps(result, ensure_ascii=False))
        old_prompt = f"""
        You are given a comparison result from Centum's band-based engine.

        STRUCTURE REQUIREMENTS
        Return exactly this structure (markdown):
        1) Overall
        2) Highlights of improvement
        3) Areas to watch
        4) Flags
        5) Personalised next steps anchored to your Centum Action Plan

        WRITING RULES
        - “Overall”: report old→new dates, number of categories improved / same / worsened, and overall net_score from the JSON.
        - “Highlights of improvement”: use result.highlights.improvements (top categories by delta). For each highlighted category, list 2–5 key biomarker transitions that improved (e.g., critical→normal, normal→good). Show old_value→new_value (no units unless present in JSON fields).
        - “Areas to watch”: include biomarkers that worsened band (good→normal or normal→critical) OR stayed in critical. Use short bullets: <Biomarker>: <from>→<to>, old_value→new_value, with one short reason (e.g., “still in critical band” or “regressed one band”).
        - “Flags”: summarise result.flags.Positive and result.flags.Caution. If both lists are empty, write “No configured flags triggered.”
        - “Personalised next steps”: pick only the sections relevant to what actually worsened or remained critical:
        • Metabolic drift (e.g., fasting_glucose worse or HbA1c critical): sleep regularity, post-meal walks, fibre-first meals, refined-carb reduction.  
        • Lipid drift (HDL down, TG up, ApoB high/normal): limit alcohol/sugars; emphasise olive oil, nuts, seeds, and fish; maintain activity.  
        • Iron trend (ferritin down): iron-rich foods + vitamin C; avoid tea/coffee with iron-rich meals.  
        • Vitamin D (high→normal or low): suggest clinician-guided dosing and re-check timing.  
        • Heavy metals (lead/mercury high/critical): fish choice guidance; consider re-testing.  
        • Thyroid antibodies (TPOAb/TgAb critical): recommend clinical follow-up (no diagnosis).  
        Keep this section to 4–6 bullet lines total.

        DATA (do not alter):
        <result_json>
        {{
        {{
        RESULT_JSON   # replace this marker with json.dumps(result, ensure_ascii=False)
        }}
        }}
        </result_json>

        WHAT TO EXTRACT
        - Dates: result.dates.old, result.dates.new
        - Category counts: result.overall.better_categories, same_categories, worse_categories
        - Overall net: result.overall.net_score
        - Category highlights: result.highlights.improvements (name + delta)
        - Per-biomarker transitions: result.transitions[*] fields:
        biomarker, category, from, to, old_value, new_value, trend
        - Flags: result.flags.Positive, result.flags.Caution

        OUTPUT STYLE
        - Headings and short paragraphs; bullets where suitable.
        - Numeric changes as “old→new”.
        - No tables. No units unless present in the JSON (do not guess).
        - Never provide clinical diagnoses; suggest discussing critical items with a clinician.
        """
        logger.info("Generating comparison summary using Grok...")
        endpoint = settings.AZURE_GROK_ENDPOINT
        model_name = settings.AZURE_GROK_DEPLOYMENT
        key = settings.AZURE_GROK_API_KEY

        old_prompt_filled = old_prompt.replace(
        "RESULT_JSON",
        json.dumps(result, ensure_ascii=False)
        )

        async with ChatCompletionsClient(endpoint, AzureKeyCredential(key),credential_scopes=["https://cognitiveservices.azure.com/.default"]) as client:
            resp = await client.complete(
            messages=[
                SystemMessage(content=system_prompt),
                UserMessage(content=old_prompt_filled)
            ],
            model=model_name,
        )
        assistant_raw = resp.choices[0].message.content

        # summary_obj = json.loads(assistant_raw)
        logger.info("Comparison summary generated successfully.")
        return assistant_raw
    except Exception as e:
        logger.error(f"Error generating comparison summary using Grok: {e}")
        return None

