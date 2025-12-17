import json
import math
import re
import copy
from typing import Any, Dict, List, Optional, Tuple, Union
from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from data_processing.biomarkers_range import centum_predefined_biomarkers_name, centum_predefined_ranges, section_to_biomarkers
from common.config import settings, logger


async def biomarker_mapping_by_llm(lab_results):
    logger.info("MApping Biomarker started")
    try:
        prompt=f"""You're expert in mapping names of biomarkers names to predefined names.
            You have given a list of predefined biomarkers range names and a list of biomarkers(blood report) with their results.
            change the blood report biomarker names to the predefined biomarker names.
            Also change the "Units" or 'unit' etc., that is given in the blood report with 'units'.
            And the "Result" or 'result' or score etc., that is given in the blood report with 'result'.
            The predefined biomakrers names are: {centum_predefined_biomarkers_name}
            The blood report is: {lab_results}

        # OUTPUT
                1) The output stricly must be JSON ouput with no extra commentaires or string.
                2)The output JSON must be like 
                {{'fasting_glucose': {{'result': '6.2', 'units': 'mmol/L'}}, 
                'hba1c': {{'result': '6.0', 'units': '%'}}, ...}}
                3) If the biomarker name is not present in the predefined biomarker names, then do not include that biomarker in the output JSON.
        """
        endpoint = settings.AZURE_GROK_ENDPOINT
        model_name = settings.AZURE_GROK_DEPLOYMENT
        key = settings.AZURE_GROK_API_KEY
        
        async with ChatCompletionsClient(endpoint, AzureKeyCredential(key), credential_scopes=["https://cognitiveservices.azure.com/.default"]) as client:
            resp = await client.complete(
            messages=[
                SystemMessage(content="You are a meticulous medical summarizer."),
                UserMessage(content=prompt)
            ],
            model=model_name,
        )
        assistant_raw = resp.choices[0].message.content
        biomarker_mapped_object = json.loads(assistant_raw)
        return biomarker_mapped_object
    except Exception as e:
        logger.error(f"Error in mapping biomarker {e}")
        return None


Number = Union[int, float]
# --- Ratio biomarkers that should ignore units entirely ---
RATIO_KEYS_IGNORE_UNIT = {"hdl_large_ldl_medium", "omega_6_omega_3_ratio"}

# Numeric bands to use if these come as a numeric ratio instead of text
RATIO_NUMERIC_BANDS = {
    "hdl_large_ldl_medium": {
        "unit": "ratio",
        "optimal": [{"min": 2.0, "inclusive_min": True}],
        "average": [{"min": 1.6, "max": 2.0, "inclusive_min": True, "inclusive_max": False}],
        "poor":    [{"max": 1.6, "inclusive_max": False}],
    },
    "omega_6_omega_3_ratio": {
        "unit": "ratio",
        "optimal": [{"min": 2.0, "max": 3.0, "inclusive_min": True, "inclusive_max": True}],
        "average": [{"min": 3.0, "max": 6.0, "inclusive_min": False, "inclusive_max": True}],
        "poor":    [{"min": 6.0, "inclusive_min": False}],
    },
}

# -------------------------------------------------------------------
# Unit handling
# -------------------------------------------------------------------
# How units should be displayed in results (title-case / uppercase etc.)
DISPLAY_UNITS = {
    "miu/l": "mIU/L",
    "iu/l": "IU/L",
    "u/l": "U/L",
    "u/ml": "U/mL",
    "ku/l": "kU/L",
    "pg/ml": "pg/mL",
    "ng/ml": "ng/mL",
    "ng/l": "ng/L",
    "g/l": "g/L",
    "mg/dl": "mg/dL",
    "mmol/l": "mmol/L",
    "mol/l": "mol/L",
    "x10^9/l": "x10^9/L",
    "x10^12/l": "x10^12/L",
    "pmol/l": "pmol/L",
    "µmol/l": "µmol/L",
    "umol/l": "µmol/L",
    "µg/l": "µg/L",
    "ml/min/1.73m²": "mL/min/1.73m²",
    "fl": "fL",
    "pg": "pg",
    "l/l": "L/L",
    "%": "%",
    "ratio": "ratio",
    "pattern": "pattern",
    "profile": "profile",
    "genotype": "genotype",
}

def pretty_unit(u: Optional[str]) -> str:
    """Return a nicely-cased display unit (doesn't affect calculations)."""
    cu = canon_unit(u)
    return DISPLAY_UNITS.get(cu, u or "")


def normalize_unit(u: Optional[str]) -> str:
    """
    Normalize the *spelling* of units but do not convert values.
    - Unifies micro symbols (μ -> µ), exponents (×10^9 -> x10^9), and superscripts.
    - Removes whitespace.
    - Normalizes some surface variants like m2 -> m² (for eGFR).
    """
    if u is None:
        return ""
    s = u.strip()
    # unify micro symbols and special chars
    s = s.replace("μ", "µ")
    s = s.replace("×10^12", "x10^12").replace("×1012", "x10^12")
    s = s.replace("×10^9", "x10^9").replace("×109", "x10^9")
    s = s.replace("¹", "1").replace("²", "2").replace("³", "3").replace("⁴", "4") \
         .replace("⁵", "5").replace("⁶", "6").replace("⁷", "7").replace("⁸", "8") \
         .replace("⁹", "9").replace("⁰", "0")
    s = s.replace("m2", "m²")  # eGFR area unit
    # canonical spacing/case
    s = re.sub(r"\s+", "", s, flags=re.I)
    return s

# Units that are the same (aliases) — no numeric conversion is applied here.
UNIT_ALIASES = {
    "miu/l": "miu/l",
    "mu/l": "miu/l",
    "mul": "miu/l",
    "muil": "miu/l",
    "nmol/l": "nmol/l",
    "umol/l": "µmol/l",
    "µmol/l": "µmol/l",
    "pg/ml": "pg/ml",
    "ng/ml": "ng/ml",
    "ng/l": "ng/l",
    "g/l": "g/l",
    "mg/dl": "mg/dl",
    "mmol/l": "mmol/l",
    "mol/l": "mol/l",
    "x10^9/l": "x10^9/l",
    "x10^12/l": "x10^12/l",
    "u/l": "u/l",
    "iu/l": "iu/l",
    "pmol/l": "pmol/l",
    "µg/l": "µg/l",
    "ug/l": "µg/l",
    "ml/min/1.73m²": "ml/min/1.73m²",
    "ml/min/1.73m2": "ml/min/1.73m²",
}

# Markers that are inherently unitless — never convert these
UNITLESS_EXPECTED = {"", "ratio", "index", "score", "pattern", "profile", "genotype"}

# Numeric conversion factors between canonical units
# factor means: value_in_to = value_in_from * factor
UNIT_CONVERSIONS: Dict[Tuple[str, str], float] = {
    ("mg/dl", "g/l"): 0.01,
    ("ng/ml", "ng/l"): 1000.0,
    ("pg/ml", "ng/dl"): 0.1,        # 1 ng/dL = 10 pg/mL
    ("pg/ml", "ng/l"): 1.0,
    ("miu/l", "miu/l"): 1.0,

    ("umol/l", "µmol/l"): 1.0,
    ("µmol/l", "mmol/l"): 0.001,
    ("umol/l", "nmol/l"): 1000.0,
    ("µmol/l", "nmol/l"): 1000.0,
    ("nmol/l", "µmol/l"): 0.001,

        # NEW: handle nmol/L <-> pmol/L for free testosterone etc.
    ("nmol/l", "pmol/l"): 1000.0,
    ("pmol/l", "nmol/l"): 0.001,

    ("µg/l", "ng/ml"): 1.0,
    ("ng/ml", "µg/l"): 1.0,
}

# Analyte-specific unit overrides (precedence over generic conversions).
ANALYTE_UNIT_OVERRIDES: Dict[str, List[Tuple[str, str, float]]] = {
    # c-peptide often in ng/mL lab units; predefined is nmol/L
    # Approx factor uses MW ≈ 3020 g/mol: 1 ng/mL ≈ 0.331 nmol/L
    "c_peptide": [("ng/ml", "nmol/l", 0.331)],
    # reverse T3
    "reverse_t3": [
        ("pg/ml",  "ng/dl", 0.1),
        ("nmol/l", "ng/dl", 65.1),   # using MW ≈ 650.97 g/mol
    ],
    # soluble transferrin receptor
    "soluble_transferrin_receptor": [
        ("mg/dl", "mg/l", 10.0),
        ("µg/ml", "mg/l", 1.0),
        ("ug/ml", "mg/l", 1.0),
        ("ng/ml", "mg/l", 0.001),
        ("µg/l",  "mg/l", 0.001),
        ("ug/l",  "mg/l", 0.001),
    ],
    # Lp(a): mg/dL -> g/L
    "lpa": [("mg/dl", "g/l", 0.01)],
    # Mercury: µmol/L -> nmol/L
    "mercury_blood": [("µmol/l", "nmol/l", 1000.0), ("umol/l", "nmol/l", 1000.0)],
    # Uric acid: µmol/L -> mmol/L
    "uric_acid": [("µmol/l", "mmol/l", 0.001), ("umol/l", "mmol/l", 0.001)],
    # ACTH: pg/mL -> ng/L
    "acth": [("pg/ml", "ng/l", 1.0)],
    # Prolactin: ng/mL -> µg/L
    "prolactin": [
        ("ng/ml", "µg/l", 1.0),
        ("miu/l", "µg/l", 0.0212),   # ← NEW: 1 mIU/L = 0.0212 µg/L
    ],

     "ca125": [
        ("u/l",  "u/ml", 0.001),
        ("ku/l", "u/ml", 1.0),
    ],

    # AFP (alpha-fetoprotein): your expected ng/mL; many labs use µg/L
    # 1 µg/L == 1 ng/mL (numerically identical)
    "afp_alpha_fetoprotein": [
        ("µg/l", "ng/ml", 1.0),
    ],

    # IGF-1: expected nmol/L; labs may report µg/L
    # Using MW ≈ 7.649 kDa  ->  nmol/L ≈ µg/L * (1000 / 7649) ≈ 0.1308
    "igf_1": [
        ("µg/l", "nmol/l", 1000.0 / 7649.0),
        # optional, covers ng/mL if it appears:
        ("ng/ml", "nmol/l", 1000.0 / 7649.0),
    ],
}

def canon_unit(u: Optional[str]) -> str:
    """
    Return the canonical form of a unit string (no numeric conversion).
    Also treats common "no unit" tokens as empty.
    """
    nu = normalize_unit(u).lower()
    if nu in {"", "-", "—", "na", "n/a", "none"}:
        return ""
    return UNIT_ALIASES.get(nu, nu)

def try_convert(value: Number, from_unit: str, to_unit: str, analyte_key: str) -> Tuple[Optional[Number], Optional[str]]:
    """
    Convert `value` from `from_unit` to `to_unit` for a given `analyte_key`.

    Strategy:
    1) Try analyte-specific overrides first (handles ambiguous lab practices).
    2) Fall back to generic `UNIT_CONVERSIONS`.
    3) If no path, return (None, "no_conversion:...").
    """
    f = canon_unit(from_unit)
    t = canon_unit(to_unit)
    if f == t:
        return value, None
    # analyte-specific first
    for k, overrides in ANALYTE_UNIT_OVERRIDES.items():
        if k == analyte_key and overrides:
            for _from, _to, factor in overrides:
                if canon_unit(_from) == f and canon_unit(_to) == t:
                    return value * factor, None
    # generic
    factor = UNIT_CONVERSIONS.get((f, t))
    if factor is not None:
        return value * factor, None
    return None, f"no_conversion:{from_unit}->{to_unit}"

# -------------------------------------------------------------------
# Range handling
# -------------------------------------------------------------------

def _as_float(x: Any) -> Optional[float]:
    """Safely coerce a value to float; returns None for non-parsable values."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        s = str(x).strip().replace(",", "")
        return float(s)
    except Exception:
        return None

def _in_range(v: float, rng: Dict[str, Any]) -> bool:
    """
    Check whether v falls in rng.

    rng keys supported:
      - min / max (numeric bounds)
      - inclusive_min / inclusive_max (defaults True)
      - equal_to (exact match; overrides min/max if present)
    """
    if "equal_to" in rng and rng["equal_to"] is not None:
        return math.isclose(v, float(rng["equal_to"]), rel_tol=0, abs_tol=1e-9)
    lo = rng.get("min", None)
    hi = rng.get("max", None)
    inc_lo = rng.get("inclusive_min", True)
    inc_hi = rng.get("inclusive_max", True)
    if lo is not None:
        if inc_lo:
            if not (v >= lo):
                return False
        else:
            if not (v > lo):
                return False
    if hi is not None:
        if inc_hi:
            if not (v <= hi):
                return False
        else:
            if not (v < hi):
                return False
    return True

def _choose_branch(spec: Dict[str, Any], sex: Optional[str], age: Optional[int]) -> Dict[str, Any]:
    """
    Select the sex/age-specific sub-branch of a biomarker spec if present.
    - Sex selection: uses top-level "M"/"F" dicts.
    - Age selection: supports bands "<N", "≤N", ">=N", "≥N" and "A-B" (inclusive).
    If no branch applies, returns the original spec. Inherit parent "unit" if child lacks one.
    """
    spec = copy.deepcopy(spec)
    parent_unit = spec.get("unit")

    # 1) Sex-based
    if sex and sex.upper() in spec and isinstance(spec[sex.upper()], dict):
        child = copy.deepcopy(spec[sex.upper()])
        if "unit" not in child and parent_unit:
            child["unit"] = parent_unit
        spec = child
        parent_unit = spec.get("unit", parent_unit)

    # 2) Age-based bands
    if age is None:
        return spec

    candidates: List[Tuple[int, int, Dict[str, Any]]] = []  # (lo, hi, branch)
    for k, v in list(spec.items()):
        if not isinstance(v, dict):
            continue
        ks = str(k).strip()

        # A-B (inclusive)
        m = re.match(r"^(\d+)\s*-\s*(\d+)$", ks)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo <= age <= hi:
                branch = copy.deepcopy(v)
                if "unit" not in branch and parent_unit:
                    branch["unit"] = parent_unit
                candidates.append((lo, hi, branch))
            continue

        # <N or ≤N
        m = re.match(r"^<\s*(\d+)$", ks)
        if m and age < int(m.group(1)):
            branch = copy.deepcopy(v)
            if "unit" not in branch and parent_unit:
                branch["unit"] = parent_unit
            candidates.append((-10**9, int(m.group(1)) - 1, branch))
            continue
        m = re.match(r"^[≤]\s*(\d+)$", ks)
        if m and age <= int(m.group(1)):
            branch = copy.deepcopy(v)
            if "unit" not in branch and parent_unit:
                branch["unit"] = parent_unit
            candidates.append((-10**9, int(m.group(1)), branch))
            continue

        # ≥N or >=N
        m = re.match(r"^(≥|>=)\s*(\d+)$", ks)
        if m and age >= int(m.group(2)):
            branch = copy.deepcopy(v)
            if "unit" not in branch and parent_unit:
                branch["unit"] = parent_unit
            candidates.append((int(m.group(2)), 10**9, branch))
            continue

    if candidates:
        lo, hi, best = min(candidates, key=lambda t: (t[1] - t[0], -t[0]))
        return best

    return spec

def _collect_ranges(d: Dict[str, Any]) -> Tuple[str, Any, Dict[str, Any]]:
    """
    Normalize a biomarker spec into:
    - expected_unit: str (may be empty)
    - categorical_or_none: "categorical" if the spec uses strings; else None
    - ranges_dict: dict with keys {optimal, average, poor} if present

    Special case:
    - If "optimal" is absent but the dict has root-level "min"/"max",
      treat that as a single 'optimal' band.
    """
    unit = d.get("unit", "")

    def _is_cat_value(v: Any) -> bool:
        if isinstance(v, str):
            return True
        if isinstance(v, list):
            return any(not isinstance(it, dict) for it in v)
        return False

    if any(_is_cat_value(d.get(k)) for k in ("optimal", "average", "poor")):
        return unit, "categorical", {
            "optimal": d.get("optimal"),
            "average": d.get("average"),
            "poor":    d.get("poor"),
        }

    if "optimal" not in d and "min" in d and "max" in d:
        return unit, None, {
            "optimal": {
                "min": float(d["min"]),
                "max": float(d["max"]),
                "inclusive_min": True,
                "inclusive_max": True,
            }
        }

    return unit, None, {k: d.get(k) for k in ("optimal", "average", "poor") if k in d}

def _to_range_list(x: Any) -> List[Dict[str, Any]]:
    """Turn a band spec into a list of range dicts; ignores non-dict items."""
    if x is None:
        return []
    if isinstance(x, dict):
        return [x]
    if isinstance(x, list):
        out = []
        for item in x:
            if isinstance(item, dict):
                out.append(item)
        return out
    return []

def _classify_numeric(v: float, ranges: Dict[str, Any]) -> Optional[str]:
    """
    Classify a numeric value v using bands in priority order:
        "optimal" -> "average" -> "poor"
    Returns the matched label or None if no range matches.
    """
    for label in ("optimal", "average", "poor"):
        lst = _to_range_list(ranges.get(label))
        valid_any = False
        for r in lst:
            lo = r.get("min", None); hi = r.get("max", None)
            if (lo is not None and hi is not None) and (float(lo) > float(hi)):
                continue
            valid_any = True
            if _in_range(v, r):
                return label
        if not lst or not valid_any:
            continue
    return None

def _classify_categorical(raw_value: str, cat_spec: Dict[str, Any]) -> Optional[str]:
    """
    Classify a categorical value (string) by case-insensitive match.
    Exact match or substring containment is allowed (tolerant of minor wording).
    """
    val = (raw_value or "").strip().lower()
    for label in ("optimal", "average", "poor"):
        spec_val = cat_spec.get(label)
        if spec_val is None:
            continue
        if isinstance(spec_val, list):
            for s in spec_val:
                ss = str(s).strip().lower()
                if val == ss or ss in val or val in ss:
                    return label
        else:
            ss = str(spec_val).strip().lower()
            if val == ss or ss in val or val in ss:
                return label
    return None

# -------------------------------------------------------------------
# Name normalization / aliases
# -------------------------------------------------------------------

NAME_ALIASES = {
    "iron": "iron_serum",
    "cortisol_serum,_8am": "cortisol",
    "nt-probnp": "nt_probnp",
    "lp-pla2": "lp_pla2",
    "hdl-c": "hdl_cholesterol",
    "ldl-c": "ldl_cholesterol_direct",
    "non-hdl": "non_hdl_cholesterol",
}

def canon_name(name: str) -> str:
    """
    Canonicalize a biomarker name:
    - Lowercase, replace non [a-z0-9_] with underscores, collapse repeats,
      then apply NAME_ALIASES.
    """
    k = name.strip().lower()
    k = re.sub(r"[^a-z0-9_]+", "_", k)
    k = re.sub(r"_+", "_", k).strip("_")
    return NAME_ALIASES.get(k, k)

# -------------------------------------------------------------------
# Main API
# -------------------------------------------------------------------
async def classify_report(
    predefined_ranges: Dict[str, Any],
    report: Dict[str, Dict[str, str]],
    sex: Optional[str] = None,
    age: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Classify each entry in `report` against `predefined_ranges`.

    Returns
    -------
    {
      "summary": {
        "optimal": int,
        "normal": int,   # average -> normal
        "poor": int,
        "invalid": int,
        "invalid_breakdown": {
          "unknown_marker": int,
          "unit_mismatch": int,
          "non_numeric_value": int,
          "no_band_match": int,
          "unclassified_categorical": int,
        }
      },
      "optimal_biomarkers": {...},
      "normal_biomarkers": {...},
      "poor_biomarkers":   {...},
      "invalid_biomarkers": { ... },
      "meta": {"sex": sex, "age": age}
    }
    """
    counts = {"optimal": 0, "normal": 0, "poor": 0, "invalid": 0}
    invalid_breakdown = {
        "unknown_marker": 0,
        "unit_mismatch": 0,
        "non_numeric_value": 0,
        "no_band_match": 0,
        "unclassified_categorical": 0,
    }

    sections = {
        "optimal_biomarkers": {},
        "normal_biomarkers": {},
        "poor_biomarkers": {},
    }
    invalid_out: Dict[str, Dict[str, Any]] = {}

    def _label_to_section(lbl: str) -> Optional[str]:
        return {"optimal": "optimal_biomarkers",
                "average": "normal_biomarkers",
                "poor": "poor_biomarkers"}.get(lbl)

    def _mark_invalid(key: str, reason: str, payload: Dict[str, Any]):
        counts["invalid"] += 1
        if reason in invalid_breakdown:
            invalid_breakdown[reason] += 1
        else:
            invalid_breakdown.setdefault(reason, 0)
            invalid_breakdown[reason] += 1
        invalid_out[key] = {"reason": reason, **payload}

    for raw_key, entry in report.items():
        key = canon_name(raw_key)
        lab_val = _as_float(entry.get("result"))
        lab_unit = canon_unit(entry.get("units"))

        # Unknown marker
        if key not in predefined_ranges:
            _mark_invalid(key, "unknown_marker", {})
            continue

        # Choose branch and collect ranges/unit
        spec = _choose_branch(copy.deepcopy(predefined_ranges[key]), sex, age)
        expected_unit, categorical, band_spec = _collect_ranges(spec)
        # ---- RATIO SHORT-CIRCUIT (ignore units for these keys) ----
        if key in RATIO_KEYS_IGNORE_UNIT:
            num = _as_float(entry.get("result"))
            if num is not None:
                # Prefer our numeric bands; if not present, fall back to whatever bands came from spec
                ratio_ranges = RATIO_NUMERIC_BANDS.get(key) or band_spec or {}
                label = _classify_numeric(num, ratio_ranges)
                if label is not None:
                    mapped = "normal" if label == "average" else label
                    counts[mapped] += 1
                    sec = _label_to_section(label)
                    if sec:
                        sections[sec][key] = {
                            "value": round(num, 6),
                            "unit": pretty_unit("ratio"),          # force "ratio" for display
                            "expected_unit": pretty_unit("ratio"),  # and ignore whatever the input had
                        }
                else:
                    _mark_invalid(key, "no_band_match", {
                        "value": round(num, 6),
                        "unit": pretty_unit(entry.get("units")),
                        "expected_unit": pretty_unit("ratio"),
                    })
                continue  # IMPORTANT: skip the normal unit-conversion path entirely
        # ---- end RATIO SHORT-CIRCUIT ----

        exp_unit = canon_unit(expected_unit)

        # Categorical markers skip numeric conversion entirely
        if categorical == "categorical":
            label = _classify_categorical(str(entry.get("result")), band_spec)
            if not label:
                _mark_invalid(key, "unclassified_categorical", {
                    "value": entry.get("result"),
                    "unit": entry.get("units"),
                    "expected_unit": expected_unit
                })
            else:
                mapped = "normal" if label == "average" else label
                counts[mapped] += 1
                sec = _label_to_section(label)
                if sec:
                    # sections[sec][key] = {
                    #     "value": entry.get("result"),
                    #     "unit": entry.get("units"),
                    #     "expected_unit": expected_unit
                    # }
                    sections[sec][key] = {
                        "value": entry.get("result"),
                        "unit": pretty_unit(entry.get("units")),
                        "expected_unit": pretty_unit(expected_unit),
                    }
            continue

        # Numeric markers
        if lab_val is None:
            _mark_invalid(key, "non_numeric_value", {
                "value": entry.get("result"),
                "unit": entry.get("units"),
                "expected_unit": expected_unit
            })
            continue

        # Unit conversion (with unitless support)
        final_val = lab_val
        final_unit = lab_unit
        unit_note = None

        # Consider this marker unitless if expected unit is in UNITLESS_EXPECTED
        # or name looks like a ratio/index/score
        name_suggests_unitless = bool(re.search(r"(ratio|index|score)\b", key))
        is_unitless = (exp_unit in UNITLESS_EXPECTED) or name_suggests_unitless

        if is_unitless:
            # Do not convert; keep input unit (often blank/dash); optionally adopt exp_unit label
            final_unit = exp_unit or final_unit  # e.g., "ratio" or ""
        else:
            if exp_unit:
                if lab_unit != exp_unit:
                    converted, err = try_convert(lab_val, lab_unit, exp_unit, key)
                    if converted is not None:
                        final_val = converted
                        final_unit = exp_unit
                        unit_note = f"converted:{lab_unit}->{exp_unit}"
                    else:
                        _mark_invalid(key, "unit_mismatch", {
                            "value": lab_val,
                            "unit": entry.get("units"),
                            "expected_unit": expected_unit,
                            "detail": err
                        })
                        continue
            # else: no expected unit provided; keep as-is

        # Range classification
        raw_label = _classify_numeric(final_val, band_spec)
        if raw_label is None:
            payload = {
                "value": round(final_val, 6),
                "unit": pretty_unit(final_unit or entry.get("units")),
                "expected_unit": pretty_unit(expected_unit),
            }
            if unit_note:
                payload["detail"] = unit_note
            _mark_invalid(key, "no_band_match", payload)
        else:
            mapped = "normal" if raw_label == "average" else raw_label
            counts[mapped] += 1
            sec = _label_to_section(raw_label)
            if sec:
                obj = {
                    "value": round(final_val, 6),
                    "unit": pretty_unit(final_unit or entry.get("units")),
                    "expected_unit": pretty_unit(expected_unit),
                }
                if unit_note:
                    obj["detail"] = unit_note
                sections[sec][key] = obj

    # return {
    #     "summary": {**counts, "invalid_breakdown": invalid_breakdown},
    #     "optimal_biomarkers": sections["optimal_biomarkers"],
    #     "normal_biomarkers": sections["normal_biomarkers"],
    #     "poor_biomarkers": sections["poor_biomarkers"],
    #     "invalid_biomarkers": invalid_out,
    #     "meta": {"sex": sex, "age": age},
    # }

    if not sections["optimal_biomarkers"] and not sections["normal_biomarkers"] and not sections["poor_biomarkers"]:
        return None

    return {
        "counts": {**counts, "invalid_breakdown": invalid_breakdown},
        "good": sections["optimal_biomarkers"],
        "normal": sections["normal_biomarkers"],
        "critical": sections["poor_biomarkers"],
        "invalid_biomarkers": invalid_out,
    }


# Generate Clinical Summary
async def generate_clinical_summary(gender, section_classification_result, questionnaire):
    logger.info("generate clinical summary started")
    try:
        # criticl concers-> 
        prompt =  f"""You're centum blood report summarizre AI.
    ## YOUR TASK
        Your task is to provde a json summary of the blood report using the biomarkers given with specific to each section of his/her health like metabolic_and_blood_sugar,lipid_and_cardiovascular etc., For every section provide me with two values findings,interpretation . The biomarkers are already calssified into optimal, normal and poor.
        For every section you need to provide me with the findings and interpretation of the biomarkers. Where findings will include which biomarkers are optimal, normal and poor.
        You will also be provided with patient personal questions, read them carefully. 
        After reading the patient questionaries give a action_plan which will contain four values diet(do's and dont), exercise(do's and dont), sleep(do's and dont) and supplement(do's and dont).
        Give me summary of his overall health.
        After that also provide me Critical Concers that the patient need to look after(if any).
        Message will contain the exception or the issue that you faced while generating the report.
    #  INPUT
        ## User Information
            user gender : {gender}
            Blood Report classify data : {section_classification_result}
            Patient Questionaries : {questionnaire}

    
    # OUTPUT
        1) The output stricly must be JSON ouput with no extra commentaires or string.
        2) The JSON must contains  action_plan,critical_concerns,summary,message,.
            for e.g., {{ 
                section_summary:{{
                    metabolic_and_blood_sugar:{{'findings':'Fasting glucose (5.8 mmol/L), HbA1c (5.6%), HOMA-IR (4.1), and OGTT (8.1 
                    mmol/L) are all at the higher end of normal, indicating early insulin resistance. Leptin is within 
                    range.
                    'interpretaion':''You are not diabetic, but you are at increased risk for future diabetes.'                            
                    }}
                    lipid_and_cardiovascular:{{'findings':'Total cholesterol (5.8), LDL (3.6), triglycerides (2.1), ApoB (1.35), Lp(a) (45), and 
                                                            remnant cholesterol (0.9) are above optimal. LDL pattern B and HDL large/LDL medium ratio (1.4) 
                                                            indicate higher risk.',
                    'interpretation':' Elevated risk for heart disease, especially with your family history.'
                    }},
                    .
                    .
                }}

                action_plan:{{
                    diet:{{'do':["eat vegetables","drink more water",...],"dont":["stop eating sugar",...],"summary":"Shift toward a Mediterranean-style pattern: plant ...","why_this_matters_for_you":"Your panel shows elevated LDL, ApoB, triglycerides, insulin resistance ...", "recommended_foods" : ["Fatty fish (salmon, sardines, mackerel) – 2–3 meals/week to raise your low omega-3 index (5.2 %; goal > 8 %)", "....", "...."],"foods_to_limit" : ["Red & processed meats – cut to ≤1 serve/week; lowers saturated fat driving LDL & ApoB. ","....", "...." ] }}                    
                    exercise:{{'do':["include cardion","yoga",...],"dont":["stop heavy lifting",...],"summary":"Increase daily movement, especially morning light...","why_this_matters_for_you":"Regular exercise improves insulin sensitivity, lowers blood pressure ...", "recommended_exercises" : ["Cardio: Brisk walking or cycling 30 min, 5 days/week (≥150 min). Proven to lower HOMA-IR and triglycerides.", "Strength training: 2–3 times/week to improve muscle mass and metabolic rate.", "....","... "], "activities_to_limit" : ["Prolonged sitting >60 min without movement break. ", "....", "...."] }}
                    sleep:{{'do':["take proper 8 hour of sleep",...],"dont":["do not sleep in light",...],"summary":"Aim for 7-9 hours of quality sleep per night...","why_this_matters_for_you":"Good sleep supports metabolic health, lowers inflammation ...", "recommended_sleep" : ["Target 7–8 h/night (currently 6–7 h)", "....", "....."], "sleep_hygiene_tips" : ["Screen Time: Shut devices 1 h before bed ", "....", "...."] }}
                    supplement:{{'do':["protein powder","vitamin D",...],"dont":["vitamin B12",...],"summary":"Focus on correcting your vitamin D and omega-3 levels, lowering ...","why_this_matters_for_you":"These recommendations are based on your specific biomarker results—addressing your vitamin D and omega-3 deficits ...", "recommended_supplements" : ["Vitamin D3: Take 2,000 IU daily with a meal that contains some healthy fat...", "....", "..."], "supplements_to_limit" : ["Avoid high-dose multivitamins, as your B-vitamins and minerals are ...", "....", "...."]}}
                }}
                summary:"Your overall blood report suggest that......"
                critical_concerns:["your blood sugar is ver high consult doctor now......","stop smoking "]
                message:"the range of this biomarker are confusing.."
            }}
        3) If some section do not have any data then do not include that section in the output.
    """
        endpoint = settings.AZURE_GROK_ENDPOINT
        model_name = settings.AZURE_GROK_DEPLOYMENT
        key = settings.AZURE_GROK_API_KEY
        
        async with ChatCompletionsClient(endpoint, AzureKeyCredential(key),credential_scopes=["https://cognitiveservices.azure.com/.default"]) as client:
            resp = await client.complete(
            messages=[
                SystemMessage(content="You are a meticulous medical summarizer."),
                UserMessage(content=prompt)
            ],
            model=model_name,
        )
        assistant_raw = resp.choices[0].message.content
        biomarker_mapped_object = json.loads(assistant_raw)
        return biomarker_mapped_object
    except Exception as e:
        logger.error(f"Error in generate clinical summary {e}")


async def classify_by_section(sections_map, results, include_invalid=True, include_missing=False):
    """
    sections_map: dict like your `list` mapping section -> [biomarker keys]
    results: your `output` dict from the classifier
    """
    # quick handles into the results
    opt  = set(results.get("good",  {}).keys())
    norm = set(results.get("normal",   {}).keys())
    poor = set(results.get("critical",  {}).keys())
    inv  = set(results.get("invalid_biomarkers",  {}).keys())

    out = {}
    for section, markers in sections_map.items():
        bucket = {
            "normal":  [],
            "optimal": [],
            "poor":    []
        }
        if include_invalid:
            bucket["invalid"] = []
        if include_missing:
            bucket["missing"] = []

        for m in markers:
            if m in norm:
                bucket["normal"].append(m)
            elif m in opt:
                bucket["optimal"].append(m)
            elif m in poor:
                bucket["poor"].append(m)
            elif m in inv and include_invalid:
                bucket["invalid"].append(m)
            elif include_missing:
                bucket["missing"].append(m)

        out[section] = bucket
    return out


# Report Generation Pipeline
async def report_generation_pipeline(gender, age, lab_results, questionaries):
    try:
        gender = "M" if gender.lower() == "male" else "F" if gender.lower() == "female" else None
        # llm_mapped_biomarker_obj = await biomarker_mapping_by_llm(lab_results)

        classification_result = await classify_report(centum_predefined_ranges, lab_results, sex=gender, age=int(age))
        if not classification_result:
            return None
        
        section_classification_result = await classify_by_section(section_to_biomarkers, classification_result, include_invalid=False, include_missing=False)
        summry_obj = await generate_clinical_summary(gender, section_classification_result, questionaries)
        
        if not summry_obj:
            return None
        
        return {
            "counts" : classification_result["counts"],
            "summary" : summry_obj["summary"],
            "critical" : classification_result["critical"],
            "normal" : classification_result["normal"],
            "good" : classification_result["good"],
            "invalid_biomarkers" : classification_result["invalid_biomarkers"],
            "critical_concerns" : summry_obj["critical_concerns"],
            "action_plan" : summry_obj["action_plan"],
            "section_summary" : summry_obj["section_summary"]
        }
    except Exception as e:
        logger.error(f"Error in report generation pipeline {e}")
        return None
